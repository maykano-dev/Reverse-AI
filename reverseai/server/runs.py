"""Background run manager for live, streamable, durable investigations.

Starting a job spawns a daemon thread running the agent. Every event is appended
to a per-job JSONL log, which gives us three things at once:

  * live streaming over SSE
  * replay after a reconnect (``?after=N``)
  * survival across a page reload or a server restart

Conversation state is persisted too (messages, evidence, target, workspace), so
a follow-up continues the same work instead of silently starting over.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agent import Agent, Permission, get_provider
from ..agent.conversation import Conversation
from ..agent.store import JobStore
from ..checkpoints import CheckpointStore
from ..verify.corpus import CorpusStore

_PERM = {"read": Permission.READ, "execute": Permission.EXECUTE, "write": Permission.WRITE}
_TERMINAL = {"final", "error"}

_MAX_RUNS = 300       # keep recent run event-streams in memory
_MAX_CONVOS = 150     # keep recent conversations resumable in memory
CLIENT_VERSION = 2    # bump when the browser needs a compatibility shim


def preview_compat_event(event: dict[str, Any], legacy: bool) -> dict[str, Any] | None:
    """Old shells cannot render the new preview card.

    They do, however, open the Preview panel when a ``clone_website`` result
    arrives. Emit an honest "Opening the live preview" event for those clients
    so a generated site is still usable without forcing a reload.
    """
    if not legacy or event.get("type") != "final" or not event.get("preview"):
        return None
    return {
        "type": "tool_result",
        "step": event.get("steps") or 1,
        "name": "clone_website",
        "ok": True,
        "permission": "read",
        "title": "Opening the live preview",
        "content": "The generated site is ready in the Preview panel.",
        "compat": "preview",
    }


@dataclass
class Run:
    job_id: str
    events: "queue.Queue[dict]" = field(default_factory=queue.Queue)
    done: threading.Event = field(default_factory=threading.Event)
    record: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    conversation_id: str | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    legacy_client: bool = False


class RunManager:
    def __init__(self, store: JobStore, memory=None, skills: list | None = None,
                 routines=None, quota=None) -> None:
        self.store = store
        self.quota = quota
        self.memory = memory
        self.skills = skills or []
        self.routines = routines
        self.corpus = CorpusStore(Path(store.dir) / "corpora")
        self._runs: dict[str, Run] = {}
        self._convos: dict[str, Any] = {}  # conversation_id -> Conversation
        self._lock = threading.Lock()

    def _evict(self) -> None:
        """Bound memory: drop oldest finished runs and oldest conversations."""
        if len(self._runs) > _MAX_RUNS:
            finished = sorted((r for r in self._runs.values() if r.done.is_set()),
                              key=lambda r: r.created_at)
            for r in finished[: len(self._runs) - _MAX_RUNS]:
                self._runs.pop(r.job_id, None)
        if len(self._convos) > _MAX_CONVOS:
            oldest = sorted(self._convos.items(),
                            key=lambda kv: getattr(kv[1], "created_at", 0))
            for cid, _ in oldest[: len(self._convos) - _MAX_CONVOS]:
                self._convos.pop(cid, None)

    # ------------------------------------------------------------------
    # Start / restore
    # ------------------------------------------------------------------
    def start(self, body: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
        """Validate + launch a turn. Returns (stream_id, conversation_id, error)."""
        goal = body.get("goal")
        if not goal:
            return None, None, "missing 'goal'"

        cid = body.get("conversation_id")
        conv = None
        if cid:
            with self._lock:
                conv = self._convos.get(cid)
            if conv is None:
                conv = self._restore(cid, body)
            if conv is None:
                return None, None, (
                    "this chat is no longer available on the server. "
                    "Start a new chat to continue.")

        if conv is None:
            budget_error = self._budget_error()
            if budget_error:
                return None, None, budget_error
            conv, cid, error = self._new_conversation(body)
            if error:
                return None, None, error

        from ..agent.job import _job_id

        stream_id = _job_id()
        legacy = int(body.get("client") or 1) < CLIENT_VERSION
        run = Run(job_id=stream_id, conversation_id=cid, legacy_client=legacy)
        with self._lock:
            self._runs[stream_id] = run
            self._evict()

        # Truncate any stale log for this id (ids are random, but be strict).
        try:
            (self.store.events_dir / f"{stream_id}.jsonl").write_text("", "utf-8")
        except OSError:
            pass

        def _worker():
            def on_event(ev: dict) -> None:
                compat = preview_compat_event(ev, run.legacy_client)
                if compat is not None:
                    self.store.append_event(stream_id, compat)
                    run.events.put(compat)
                self.store.append_event(stream_id, ev)
                run.events.put(ev)

            try:
                job = conv.run_turn(goal, on_event=on_event, stop_event=run.cancel,
                                    attachments=body.get("attachments") or [])
                job.id = stream_id  # align stored id with the streamed one
                job.conversation_id = cid
                # Persist a delivered artifact only when the delivery gate
                # allowed it. A blocked candidate stays in the workspace, but is
                # not exposed as a delivered file.
                if job.delivery.get("allowed") and job.artifact:
                    mp = job.artifact_meta.get("path")
                    if mp:
                        self.store.save_artifact(job.id, mp)
                self.store.save(job)
                self._save_conversation(cid, conv, body)
                self._consume_quota(job, body)
                run.record = job.to_dict()
            except Exception as exc:  # pragma: no cover - defensive
                err = {"type": "error", "error": f"run crashed: {exc}"}
                self.store.append_event(stream_id, err)
                run.events.put(err)
            finally:
                run.done.set()

        threading.Thread(target=_worker, daemon=True).start()
        return stream_id, cid, None

    def _new_conversation(self, body: dict[str, Any]):
        perm_name = str(body.get("permission", "write")).lower()
        perm = _PERM.get(perm_name)
        if perm is None:
            return None, None, "permission must be read|execute|write"
        from ..agent.templates import resolve_template
        template = resolve_template(body.get("template"), body.get("goal"))
        provider_name = os.environ.get("REVERSEAI_PROVIDER") or body.get("provider", "deepseek")
        try:
            provider = get_provider(provider_name)
        except Exception as exc:
            return None, None, f"provider error: {exc}"

        cid = _new_id("conv")
        agent = Agent(provider, max_permission=perm,
                      max_steps=max(1, min(int(body.get("max_steps", 24)), 64)),
                      template=template, memory=self.memory, skills=self.skills,
                      mode=body.get("mode"))
        workspace = str(self.store.workspaces_dir / cid)
        conv = agent.open(target_path=body.get("target"),
                          project_dir=body.get("project_dir"),
                          workspace=workspace)
        conv.ctx.extra["routine_store"] = self.routines
        conv.ctx.extra["upload_root"] = str(Path(self.store.dir) / "uploads")
        conv.ctx.extra["corpus_store"] = self.corpus
        conv.ctx.extra["checkpoint_store"] = CheckpointStore(
            Path(conv.workspace).parent / "checkpoints" / Path(conv.workspace).name,
            workspace=conv.workspace)
        conv._permission = perm_name
        conv._provider_name = provider.name
        with self._lock:
            self._convos[cid] = conv
        return conv, cid, None

    def _restore(self, cid: str, body: dict[str, Any]) -> Conversation | None:
        state = self.store.load_conversation(cid)
        if not state:
            return None
        perm_name = str(state.get("permission") or "write").lower()
        perm = _PERM.get(perm_name, Permission.WRITE)
        provider_name = (os.environ.get("REVERSEAI_PROVIDER")
                         or state.get("provider")
                         or body.get("provider")
                         or "deepseek")
        try:
            provider = get_provider(provider_name)
        except Exception:
            return None
        agent = Agent(provider, max_permission=perm,
                      max_steps=max(1, min(int(body.get("max_steps", 24)), 64)),
                      template=state.get("template") or "general",
                      memory=self.memory, skills=self.skills,
                      mode=state.get("mode") or body.get("mode"))
        conv = Conversation.from_state(agent, state)
        conv.ctx.extra["routine_store"] = self.routines
        conv.ctx.extra["upload_root"] = str(Path(self.store.dir) / "uploads")
        conv.ctx.extra["corpus_store"] = self.corpus
        conv.ctx.extra["checkpoint_store"] = CheckpointStore(
            Path(conv.workspace).parent / "checkpoints" / Path(conv.workspace).name,
            workspace=conv.workspace)
        conv._permission = perm_name
        conv._provider_name = provider.name
        with self._lock:
            self._convos[cid] = conv
            self._evict()
        return conv

    def _save_conversation(self, cid: str, conv, body: dict[str, Any]) -> None:
        try:
            state = conv.to_state()
            state["permission"] = getattr(conv, "_permission",
                                          str(body.get("permission", "write")))
            state["provider"] = getattr(conv, "_provider_name",
                                        os.environ.get("REVERSEAI_PROVIDER", "deepseek"))
            self.store.save_conversation(cid, state)
        except Exception:
            pass

    def _consume_quota(self, job, body: dict[str, Any]) -> None:
        quota = self.quota
        token = str(body.get("_quota_token") or "")
        if quota is None or not token or not quota.policy.enabled():
            return
        try:
            usage = job.usage or {}
            quota.consume(token, runs=1,
                          tokens=int(usage.get("total_tokens", 0) or 0),
                          cost_usd=float(usage.get("cost_usd", 0) or 0))
        except Exception:
            pass

    def _budget_error(self) -> str | None:
        usage = self.store.usage_summary()
        budget = usage.get("budget_usd")
        cost = usage.get("cost_usd") or 0.0
        if budget is not None and cost >= budget:
            return (f"monthly budget reached (${cost:.2f} of ${budget:.2f}). "
                    "Raise REVERSEAI_MONTHLY_BUDGET or use a local model.")
        return None

    # ------------------------------------------------------------------
    # Lookups / streaming
    # ------------------------------------------------------------------
    def get(self, job_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        run = self.get(job_id)
        if run is None or run.done.is_set():
            return False
        run.cancel.set()
        return True

    def conversation(self, cid: str):
        with self._lock:
            conv = self._convos.get(cid)
        if conv is not None:
            return conv
        return self._restore(cid, {})

    def artifact_path(self, cid: str) -> str | None:
        """Path of the final modified file a conversation produced, if any."""
        conv = self.conversation(cid)
        if conv is None:
            return None
        delivery = conv.ctx.extra.get("delivery") or {}
        if not delivery.get("allowed"):
            return None
        path = conv.ctx.extra.get("modified_path")
        # Only serve a file that lives inside this conversation's workspace.
        if path and os.path.commonpath([os.path.realpath(path),
                                        os.path.realpath(conv.workspace)]) == \
                os.path.realpath(conv.workspace):
            return path if os.path.isfile(path) else None
        return None

    def stream(self, job_id: str, after: int = 0, heartbeat: float = 15.0):
        """Yield SSE-encoded bytes for a run until a terminal event.

        ``after`` replays from a durable event index, which is what lets the UI
        reconnect after a dropped connection or a page reload. Heartbeats keep
        proxies from closing a quiet stream.
        """
        run = self.get(job_id)
        if run is None and not (self.store.events_dir / f"{job_id}.jsonl").exists():
            yield _sse({"type": "error", "error": "unknown run"})
            return

        idx = max(0, int(after or 0))
        last_beat = time.monotonic()
        while True:
            rows = self.store.read_events(job_id)
            while idx < len(rows):
                ev = rows[idx]
                idx += 1
                yield _sse(ev)
                if ev.get("type") in _TERMINAL:
                    return
            if run is not None and run.done.is_set() and idx >= len(rows):
                return
            if run is None and idx >= len(rows):
                if rows and rows[-1].get("type") not in _TERMINAL:
                    yield _sse({"type": "error",
                                "error": "This run was interrupted by a server restart. "
                                         "The saved events are still available."})
                elif not rows:
                    yield _sse({"type": "error", "error": "no events for this run"})
                return
            if time.monotonic() - last_beat >= heartbeat:
                yield b": heartbeat\n\n"
                last_beat = time.monotonic()
            time.sleep(0.15)


def _new_id(prefix: str) -> str:
    import uuid

    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode("utf-8")
