"""Multi-turn conversation state.

A Conversation holds the running message history, tool context, evidence log,
and workspace across turns, so follow-up messages continue the same
investigation (same target, same modified artifacts, accumulated evidence) —
the difference between a chatbot and a stateful engineer you can keep talking to.

A conversation can also be serialized (``to_state`` / ``from_state``) so the
server can restore it after a restart or an eviction. That is what makes a
"durable turn" possible: close the tab, come back, keep going.

A one-shot ``Agent.run`` is just a Conversation with a single turn.
"""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path

from ..naming import artifact_meta
from ..security.validate import ValidationError, read_target
from ..util.text import strip_dashes
from ..checkpoints import CheckpointStore
from ..verify.corpus import CorpusStore, default_corpus_dir
from .context import compact_messages
from .evidence import Confidence, EvidenceLog, Finding
from .job import Job
from .narrative import describe_tool, plan_for
from .prompts import SYSTEM_PROMPT
from .providers.base import Message, Role, ToolCall
from .templates import prompt_addendum
from .tools import ToolContext


def make_emitter(on_event):
    """Wrap on_event so a bad callback can never break the loop."""
    if on_event is None:
        return lambda _e: None

    def _emit(event):
        try:
            on_event(event)
        except Exception:
            pass

    return _emit


def tool_perm(registry, name: str) -> str:
    tool = registry.get(name)
    return tool.permission.label if tool else "unknown"


_SAFE_EXTRA = {
    "project_dir", "modified_path", "modified_operation", "modified_label",
    "modified_turn", "last_patches", "extracted_dir", "routine_id",
    "verification", "delivery", "differential", "differential_turn",
    "mode", "strategy", "modification_plan", "last_checkpoint",
}
_GATED_OPERATIONS = {"patch", "imports", "section", "rebuild", "reimplement"}


class Conversation:
    def __init__(self, agent, target_path: str | None = None,
                 project_dir: str | None = None, workspace: str | None = None,
                 intake: bool = True, mode: str | None = None) -> None:
        self.agent = agent
        self.target_path = target_path
        self.template = getattr(agent, "template", "general")
        self.mode = (mode or getattr(agent, "mode", "") or "").strip().lower()
        self.evidence = EvidenceLog()
        if workspace:
            self.workspace = str(Path(workspace).resolve())
            Path(self.workspace).mkdir(parents=True, exist_ok=True)
            self._temp_workspace = False
        else:
            self.workspace = tempfile.mkdtemp(prefix="reverseai-conv-")
            self._temp_workspace = True

        self.ctx = ToolContext(
            job_id="",
            workspace=self.workspace,
            target_path=target_path,
            sandbox_policy=agent.sandbox_policy,
            evidence=self.evidence,
            goal="",
            memory=getattr(agent, "memory", None),
            sources=[],
            extra={
                "project_dir": project_dir or self.workspace,
                "provider": getattr(agent, "provider", None),
                "max_permission": getattr(agent, "max_permission", None),
                "delegate_depth": getattr(agent, "delegate_depth", 0),
                "skills": getattr(agent, "skills", []),
                "mediator": getattr(agent, "mediator", None),
                "all_tools": getattr(getattr(agent, "registry", None), "all", lambda: [])(),
                "corpus_store": CorpusStore(default_corpus_dir()),
                "checkpoint_store": CheckpointStore(
                    str(Path(self.workspace).parent / "checkpoints"
                        / Path(self.workspace).name),
                    workspace=self.workspace),
                "mode": self.mode,
            },
        )
        self.messages: list[Message] = [Message(Role.SYSTEM, self._system_prompt())]
        self._first = True
        self.refused: str | None = None
        self.turns = 0
        self.created_at = time.time()
        self._lock = threading.Lock()  # serialize turns on one conversation

        if target_path and intake:
            try:
                data = read_target(target_path)
                self.evidence.observed(f"target is {len(data)} bytes", source="intake")
            except ValidationError as exc:
                self.refused = f"target rejected: {exc}"

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------
    def _system_prompt(self) -> str:
        parts = [SYSTEM_PROMPT.rstrip(), "", "Current role:", prompt_addendum(self.template)]
        try:
            from ..intelligence.modes import mode_prompt
            mp = mode_prompt(self.mode)
            if mp:
                parts += ["", mp]
        except Exception:
            pass
        skills = getattr(self.agent, "skills", None) or []
        if skills:
            from .skills import skills_prompt

            block = skills_prompt(skills)
            if block:
                parts += ["", block]
        memory = getattr(self.agent, "memory", None)
        if memory is not None:
            try:
                block = memory.prompt_context()
            except Exception:
                block = ""
            if block:
                parts += ["", block]
        parts += [
            "",
            "Reasoning display: the interface shows a short, human timeline of what "
            "you do. Keep your interim notes specific and natural (what you are "
            "checking and why), never mention tool names, and do not narrate the "
            "interface itself.",
        ]
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Turns
    # ------------------------------------------------------------------
    def add_user(self, goal: str) -> None:
        """Queue a follow-up user message without running (used before run_turn)."""
        self.messages.append(Message(Role.USER, goal))
        self._first = False

    def run_turn(self, goal: str, on_event=None, stop_event=None) -> Job:
        # Serialize: a follow-up can't corrupt state while a turn is still
        # running (e.g. a long clone). It waits for the previous turn to finish.
        with self._lock:
            return self._run_turn_locked(goal, on_event, stop_event)

    def _run_turn_locked(self, goal: str, on_event=None, stop_event=None) -> Job:
        agent = self.agent
        job = Job(goal=goal, target_path=self.target_path)
        job.workspace = self.workspace
        job.template = self.template
        emit = make_emitter(on_event)
        plan = plan_for(self.template, bool(self.target_path), goal)
        emit({"type": "start", "job_id": job.id, "goal": goal,
              "target": self.target_path, "provider": agent.provider.name,
              "template": self.template, "plan": plan})

        if self.refused:
            job.status = "refused"
            job.error = self.refused
            emit({"type": "error", "error": job.error})
            return self._finish(job)

        emit({"type": "plan", "steps": plan, "template": self.template})
        self.turns += 1
        self.ctx.job_id = job.id
        self.ctx.goal = goal
        if self._first:
            self.messages.append(Message(
                Role.USER, _initial_user_message(goal, self.target_path)))
            self._first = False
        else:
            # Only add if not already queued via add_user for this goal.
            if not (self.messages and self.messages[-1].role == Role.USER
                    and self.messages[-1].content == goal):
                self.messages.append(Message(Role.USER, goal))

        job.status = "running"
        self.ctx.extra["emit"] = emit
        # Delivery is per-turn. A previous turn's artifact must not be silently
        # re-delivered by a follow-up that changed nothing.
        self.ctx.extra.pop("delivery", None)
        self._loop(job, emit, stop_event)
        if job.status not in ("cancelled", "failed"):
            self._enforce_delivery_gate(job, emit)
        job = self._finish(job)

        artifact = self.ctx.extra.get("modified_path")
        delivery = self.ctx.extra.get("delivery") or {}
        meta = artifact_meta(artifact) if artifact else {}
        # The ONLY delivery path. A gated binary modification is delivered only
        # when a behavioral test actually passed; otherwise the file is withheld.
        if meta.get("name") and delivery.get("allowed"):
            job.artifact = meta["name"]
            job.artifact_meta = meta
        else:
            job.artifact = None
            job.artifact_meta = {}
        verification = dict(self.ctx.extra.get("verification") or {})
        if verification.get("turn") not in (None, job.id):
            verification = {}
        job.verification = verification
        job.delivery = dict(delivery)
        job.mode = str(self.ctx.extra.get("mode") or self.mode or "")
        job.modification_plan = dict(self.ctx.extra.get("modification_plan") or {})
        diff = dict(self.ctx.extra.get("differential") or {})
        if self.ctx.extra.get("differential_turn") not in (None, job.id):
            diff = {}
        job.differential = diff
        if job.delivery and not job.delivery.get("allowed", True):
            reason = job.delivery.get("reason") or "the change was not verified"
            # Do not let an optimistic, unverified model claim stand as the
            # conclusion. The detailed attempts remain in the reasoning timeline
            # and the signed report.
            job.final_answer = (
                "I did not deliver the file because the change could not be "
                f"verified: {reason}. Expand the reasoning timeline for the test "
                "details and the attempts.")
        job.sources = list(self.ctx.sources)

        emit({"type": "final", "status": job.status, "answer": job.final_answer,
              "evidence_summary": self.evidence.summary(), "steps": job.steps,
              "usage": job.usage, "artifact": job.artifact,
              "artifact_meta": job.artifact_meta, "sources": job.sources,
              "verification": job.verification, "delivery": job.delivery,
              "differential": job.differential,
              "template": self.template, "plan": plan})
        return job

    def _enforce_delivery_gate(self, job: Job, emit) -> None:
        """Run verification before delivery, and block unverified binaries.

        This is a policy gate, not a suggestion. If a candidate binary exists
        without a passing behavioral test, the gate runs verify_modification. If
        no test was declared, the tool refuses, the artifact is withheld, and the
        reason is shown to the user.
        """
        modified = self.ctx.extra.get("modified_path")
        if not modified:
            return
        verification = self.ctx.extra.get("verification") or {}
        modified_turn = self.ctx.extra.get("modified_turn")
        verified_turn = verification.get("turn")
        # Nothing new to deliver this turn. A follow-up that merely asks a
        # question should not re-deliver an old file; a follow-up that runs a
        # new verification may deliver it.
        if modified_turn != job.id and verified_turn != job.id:
            return
        operation = self.ctx.extra.get("modified_operation") or "patch"
        if operation == "site":
            self.ctx.extra["verification"] = self.ctx.extra.get("verification") or {
                "verified": False,
                "kind": "site",
                "reason": "site bundle delivery does not require binary execution",
                "passed_tests": 0,
                "attempts": [],
            }
            self.ctx.extra["delivery"] = {
                "allowed": True,
                "reason": "site bundle packaged",
            }
            return
        if operation not in _GATED_OPERATIONS:
            self.ctx.extra["delivery"] = {
                "allowed": False,
                "reason": f"unsupported modification kind: {operation}",
            }
            return

        if not verification:
            info = describe_tool("verify_modification", {})
            emit({"type": "reason", "tool": "verify_modification",
                  "title": "Checking the change before delivery",
                  "detail": "No passing behavioral test is on record yet.",
                  "icon": info["icon"]})
            result = self.agent.mediator.dispatch(
                "verify_modification", {}, self.ctx)
            emit({"type": "tool_result", "name": "verify_modification",
                  "ok": result.ok, "permission": "execute",
                  "title": info["title"],
                  "content": (result.content or "")[:4000]})
            verification = self.ctx.extra.get("verification") or {}

        verified = bool(verification.get("verified")) and int(
            verification.get("passed_tests", 0) or 0) >= 1
        if verified:
            self.ctx.extra["delivery"] = {
                "allowed": True,
                "reason": "behavioral test passed in the sandbox",
            }
            return
        reason = (verification.get("reason")
                  or "no behavioral test passed in the sandbox")
        self.ctx.extra["delivery"] = {"allowed": False, "reason": reason}
        emit({"type": "delivery_blocked", "reason": reason,
              "artifact_withheld": True})
        if self.evidence is not None:
            self.evidence.observed(
                f"delivery blocked: {reason}", source="delivery_gate")

    def _loop(self, job: Job, emit, stop_event=None) -> None:
        agent = self.agent
        for step in range(1, agent.max_steps + 1):
            if stop_event is not None and stop_event.is_set():
                job.status = "cancelled"
                job.final_answer = "Stopped. Nothing else was changed."
                return
            job.steps = step
            emit({"type": "step", "step": step})
            self.messages = compact_messages(self.messages, agent.max_context_chars)
            try:
                resp = agent.provider.chat(
                    self.messages, tools=agent.registry.provider_specs(),
                    temperature=agent.temperature)
            except Exception as exc:
                job.status = "failed"
                job.error = f"provider error: {exc}"
                emit({"type": "error", "error": job.error})
                return
            _acc_usage(job, resp, agent.provider)

            self.messages.append(Message(
                Role.ASSISTANT, content=resp.content, tool_calls=resp.tool_calls))
            # Clean user-facing text (strip the AI "dash" tell); keep raw text in
            # the model's own history above so its context is unchanged.
            emit({"type": "assistant", "step": step,
                  "content": strip_dashes(resp.content),
                  "tool_calls": [{"name": tc.name, "arguments": tc.arguments}
                                 for tc in resp.tool_calls]})

            if not resp.tool_calls:
                job.final_answer = strip_dashes(resp.content or "")
                job.status = "completed"
                return

            for tc in resp.tool_calls:
                if stop_event is not None and stop_event.is_set():
                    job.status = "cancelled"
                    job.final_answer = "Stopped. Nothing else was changed."
                    return
                before = len(self.evidence.all())
                info = describe_tool(tc.name, tc.arguments)
                emit({"type": "reason", "step": step, "tool": tc.name,
                      "title": info["title"], "detail": info["detail"],
                      "icon": info["icon"]})

                result = agent.mediator.dispatch(tc.name, tc.arguments, self.ctx)
                self.messages.append(Message(
                    Role.TOOL, content=result.content,
                    tool_call_id=tc.id, name=tc.name))
                emit({"type": "tool_result", "step": step, "name": tc.name,
                      "ok": result.ok,
                      "permission": tool_perm(agent.registry, tc.name),
                      "title": info["title"],
                      "content": (result.content or "")[:4000]})
                for f in self.evidence.all()[before:]:
                    emit({"type": "finding", "tier": f.confidence.label,
                          "claim": f.claim, "source": f.source})

                sources = _result_sources(result.data)
                if sources:
                    known = {s.get("url") for s in self.ctx.sources}
                    for s in sources:
                        if s.get("url") and s["url"] not in known:
                            self.ctx.sources.append(s)
                            known.add(s["url"])
                            emit({"type": "source", **s})

        job.status = "incomplete"
        job.final_answer = job.final_answer or (
            "I reached the step limit before I could wrap this up. "
            "Ask me to continue and I'll pick up where I stopped.")

    def _finish(self, job: Job) -> Job:
        job.evidence = self.evidence
        job.audit = self.agent.mediator.audit_log()
        job.transcript = [m.to_openai() for m in self.messages]
        job.usage = dict(job.usage)
        job.sources = list(self.ctx.sources)
        job.finished_at = time.time()
        if job.status == "running":
            job.status = "failed"
        return job

    # ------------------------------------------------------------------
    # Durable state
    # ------------------------------------------------------------------
    def to_state(self) -> dict:
        return {
            "target_path": self.target_path,
            "workspace": self.workspace,
            "template": self.template,
            "mode": self.mode,
            "turns": self.turns,
            "created_at": self.created_at,
            "refused": self.refused,
            "messages": [_message_state(m) for m in self.messages],
            "evidence": [f.to_dict() for f in self.evidence.all()],
            "sources": list(self.ctx.sources),
            "extra": {k: v for k, v in self.ctx.extra.items()
                      if k in _SAFE_EXTRA and k not in ("emit",)},
        }

    @classmethod
    def from_state(cls, agent, state: dict, intake: bool = False) -> "Conversation":
        conv = cls(
            agent,
            target_path=state.get("target_path"),
            workspace=state.get("workspace"),
            intake=intake,
        )
        conv.template = state.get("template") or getattr(agent, "template", "general")
        conv.mode = state.get("mode") or getattr(agent, "mode", "") or ""
        conv.ctx.extra["mode"] = conv.mode
        conv.ctx.extra["mediator"] = getattr(agent, "mediator", None)
        conv.ctx.extra["all_tools"] = getattr(
            getattr(agent, "registry", None), "all", lambda: [])()
        conv.ctx.extra["corpus_store"] = CorpusStore(default_corpus_dir())
        conv.ctx.extra["checkpoint_store"] = CheckpointStore(
            str(Path(conv.workspace).parent / "checkpoints"
                / Path(conv.workspace).name),
            workspace=conv.workspace)
        conv.turns = int(state.get("turns") or 0)
        conv.created_at = float(state.get("created_at") or time.time())
        conv.refused = state.get("refused")
        messages = state.get("messages") or []
        if messages:
            conv.messages = [_message_from_state(m) for m in messages]
        conv.evidence = EvidenceLog()
        for row in state.get("evidence") or []:
            try:
                tier = Confidence[row.get("confidence", "observed").upper()]
            except KeyError:
                tier = Confidence.OBSERVED
            conv.evidence.add(
                row.get("claim", ""), tier,
                source=row.get("source", ""), detail=row.get("detail", ""))
        conv.ctx.evidence = conv.evidence
        conv.ctx.sources = list(state.get("sources") or [])
        conv.ctx.extra.update(state.get("extra") or {})
        conv.ctx.target_path = conv.target_path
        conv.ctx.workspace = conv.workspace
        conv.ctx.memory = getattr(agent, "memory", None)
        conv.ctx.extra["provider"] = getattr(agent, "provider", None)
        conv.ctx.extra["max_permission"] = getattr(agent, "max_permission", None)
        conv.ctx.extra["delegate_depth"] = getattr(agent, "delegate_depth", 0)
        conv.ctx.extra["skills"] = getattr(agent, "skills", [])
        if not conv.messages:
            conv.messages = [Message(Role.SYSTEM, conv._system_prompt())]
        elif conv.messages[0].role == Role.SYSTEM:
            # Refresh the prompt with current memory/skills.
            conv.messages[0] = Message(Role.SYSTEM, conv._system_prompt())
        conv._first = False
        return conv

    def close(self) -> None:
        """Remove the scratch workspace, but never a persistent one."""
        if not self._temp_workspace:
            return
        import shutil

        shutil.rmtree(self.workspace, ignore_errors=True)


def _result_sources(data) -> list[dict]:
    if not isinstance(data, dict):
        return []
    rows = data.get("sources")
    if isinstance(rows, list):
        return [r for r in rows if isinstance(r, dict) and r.get("url")]
    return []


def _message_state(m: Message) -> dict:
    return {
        "role": m.role.value,
        "content": m.content,
        "tool_calls": [{"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                       for tc in m.tool_calls],
        "tool_call_id": m.tool_call_id,
        "name": m.name,
    }


def _message_from_state(d: dict) -> Message:
    try:
        role = Role(d.get("role", "user"))
    except ValueError:
        role = Role.USER
    calls = [ToolCall(id=c.get("id", ""), name=c.get("name", ""),
                      arguments=c.get("arguments") or {})
             for c in (d.get("tool_calls") or []) if isinstance(c, dict)]
    return Message(role, content=d.get("content"), tool_calls=calls,
                   tool_call_id=d.get("tool_call_id"), name=d.get("name"))


def _initial_user_message(goal: str, target_path: str | None) -> str:
    """First user turn.

    With no target, pass the message through unchanged so the agent just talks
    naturally. Only when a file is attached do we frame it as an investigation.
    """
    if not target_path:
        return goal
    from pathlib import Path

    return (
        f"{goal}\n\n[Attached target: {Path(target_path).name} "
        f"(path: {target_path})]\n"
        "Work on a copy in the sandbox, verify your work, finish with a clear "
        "plain-language summary, and deliver the final file if you produce one."
    )


def _acc_usage(job: Job, resp, provider=None) -> None:
    u = resp.usage
    job.usage["prompt_tokens"] = job.usage.get("prompt_tokens", 0) + u.prompt_tokens
    job.usage["completion_tokens"] = job.usage.get("completion_tokens", 0) + u.completion_tokens
    job.usage["total_tokens"] = job.usage.get("total_tokens", 0) + u.total_tokens
    if provider is not None:
        from .pricing import estimate_cost

        cost = estimate_cost(provider.name, getattr(provider, "model", ""),
                             u.prompt_tokens, u.completion_tokens)
        if cost is not None:
            job.usage["cost_usd"] = round(job.usage.get("cost_usd", 0.0) + cost, 6)
