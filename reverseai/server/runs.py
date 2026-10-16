"""Background run manager for live, streamable investigations.

Starting a job spawns a daemon thread running the agent; its live events are
pushed to a per-run queue that the SSE endpoint drains. This is what lets the
web UI show the agent working step by step instead of blocking on a result.
"""

from __future__ import annotations

import os
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
        self._convos: dict[str, Any] = {}  # conversation_id -> Conversation
        self._lock = threading.Lock()

    def start(self, body: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
        """Validate + launch a turn. Returns (stream_id, conversation_id, error).

        A ``conversation_id`` in the body continues an existing conversation
        (same target, evidence, and modified artifacts); otherwise a new one is
        created from the provider/permission in the body.
        """
        goal = body.get("goal")
        if not goal:
            return None, None, "missing 'goal'"

        cid = body.get("conversation_id")
        with self._lock:
            conv = self._convos.get(cid) if cid else None

        if conv is None:
            # The AI decides its own mode, so it gets the full toolset (WRITE
            # ceiling). The model/provider is server-chosen and never exposed.
            perm = _PERM.get(body.get("permission", "write"))
            if perm is None:
                return None, None, "permission must be read|execute|write"
            try:
                provider = get_provider(os.environ.get("REVERSEAI_PROVIDER",
                                                        body.get("provider", "deepseek")))
            except Exception as exc:
                return None, None, f"provider error: {exc}"
            agent = Agent(provider, max_permission=perm,
                          max_steps=int(body.get("max_steps", 24)))
            conv = agent.open(target_path=body.get("target"),
                              project_dir=body.get("project_dir"))
            cid = _new_id("conv")
            with self._lock:
                self._convos[cid] = conv

        from ..agent.job import _job_id

        stream_id = _job_id()
        run = Run(job_id=stream_id)
        with self._lock:
            self._runs[stream_id] = run

        def _worker():
            def on_event(ev: dict) -> None:
                run.events.put(ev)
            try:
                job = conv.run_turn(goal, on_event=on_event)
                job.id = stream_id  # align stored id with the streamed one
                # Persist any delivered artifact durably, keyed by job id.
                mp = conv.ctx.extra.get("modified_path")
                if mp:
                    saved = self.store.save_artifact(job.id, mp)
                    if saved:
                        from pathlib import Path as _P
                        job.artifact = _P(mp).name
                self.store.save(job)
                run.record = job.to_dict()
            except Exception as exc:  # pragma: no cover - defensive
                run.events.put({"type": "error", "error": f"run crashed: {exc}"})
            finally:
                run.done.set()

        threading.Thread(target=_worker, daemon=True).start()
        return stream_id, cid, None

    def get(self, job_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(job_id)

    def conversation(self, cid: str):
        with self._lock:
            return self._convos.get(cid)

    def artifact_path(self, cid: str) -> str | None:
        """Path of the final modified file a conversation produced, if any."""
        conv = self.conversation(cid)
        if conv is None:
            return None
        path = conv.ctx.extra.get("modified_path")
        # Only serve a file that lives inside this conversation's workspace.
        if path and os.path.commonpath([os.path.realpath(path),
                                        os.path.realpath(conv.workspace)]) == \
                os.path.realpath(conv.workspace):
            return path if os.path.isfile(path) else None
        return None

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


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _sse(event: dict) -> bytes:
    import json

    return f"data: {json.dumps(event)}\n\n".encode("utf-8")
