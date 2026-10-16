"""Background run manager for live, streamable investigations.

Starting a job spawns a daemon thread running the agent; its live events are
pushed to a per-run queue that the SSE endpoint drains. This is what lets the
web UI show the agent working step by step instead of blocking on a result.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..agent import Agent, Permission, get_provider
from ..agent.store import JobStore

_PERM = {"read": Permission.READ, "execute": Permission.EXECUTE, "write": Permission.WRITE}
_TERMINAL = {"final", "error"}


@dataclass
class Run:
    job_id: str
    events: "queue.Queue[dict]" = field(default_factory=queue.Queue)
    done: threading.Event = field(default_factory=threading.Event)
    record: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)


class RunManager:
    def __init__(self, store: JobStore) -> None:
        self.store = store
        self._runs: dict[str, Run] = {}
        self._lock = threading.Lock()

    def start(self, body: dict[str, Any]) -> tuple[str | None, str | None]:
        """Validate + launch. Returns (job_id, error)."""
        goal = body.get("goal")
        if not goal:
            return None, "missing 'goal'"
        perm = _PERM.get(body.get("permission", "execute"))
        if perm is None:
            return None, "permission must be read|execute|write"
        provider_name = body.get("provider", "deepseek")
        try:
            provider = get_provider(provider_name)
        except Exception as exc:
            return None, f"provider error: {exc}"

        agent = Agent(provider, max_permission=perm,
                      max_steps=int(body.get("max_steps", 24)))
        # Pre-generate the job id so the caller can subscribe before it finishes.
        from ..agent.job import _job_id

        job_id = _job_id()
        run = Run(job_id=job_id)
        with self._lock:
            self._runs[job_id] = run

        def _worker():
            def on_event(ev: dict) -> None:
                run.events.put(ev)
            try:
                job = agent.run(goal, target_path=body.get("target"),
                                project_dir=body.get("project_dir"),
                                on_event=on_event)
                job.id = job_id  # align stored id with the streamed one
                self.store.save(job)
                run.record = job.to_dict()
            except Exception as exc:  # pragma: no cover - defensive
                run.events.put({"type": "error", "error": f"run crashed: {exc}"})
            finally:
                run.done.set()

        threading.Thread(target=_worker, daemon=True).start()
        return job_id, None

    def get(self, job_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(job_id)

    def stream(self, job_id: str, heartbeat: float = 15.0):
        """Yield SSE-encoded bytes for a run until a terminal event.

        Yields heartbeats during quiet periods so proxies don't time out.
        """
        run = self.get(job_id)
        if run is None:
            yield _sse({"type": "error", "error": "unknown run"})
            return

        while True:
            try:
                ev = run.events.get(timeout=heartbeat)
            except queue.Empty:
                if run.done.is_set():
                    break
                yield b": heartbeat\n\n"
                continue
            yield _sse(ev)
            if ev.get("type") in _TERMINAL:
                break
        # Drain any trailing events already queued.
        while True:
            try:
                ev = run.events.get_nowait()
            except queue.Empty:
                break
            yield _sse(ev)


def _sse(event: dict) -> bytes:
    import json

    return f"data: {json.dumps(event)}\n\n".encode("utf-8")
