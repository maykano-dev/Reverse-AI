"""Multi-turn conversation state.

A Conversation holds the running message history, tool context, evidence log,
and workspace across turns, so follow-up messages continue the same
investigation (same target, same modified artifacts, accumulated evidence) —
the difference between a chatbot and a stateful engineer you can keep talking to.

A one-shot ``Agent.run`` is just a Conversation with a single turn.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from ..security.validate import ValidationError, read_target
from .context import compact_messages
from .evidence import EvidenceLog
from .job import Job
from .prompts import SYSTEM_PROMPT
from .providers.base import Message, Role
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


class Conversation:
    def __init__(self, agent, target_path: str | None = None,
                 project_dir: str | None = None) -> None:
        self.agent = agent
        self.target_path = target_path
        self.evidence = EvidenceLog()
        self.workspace = tempfile.mkdtemp(prefix="reverseai-conv-")
        self.ctx = ToolContext(
            job_id="",
            workspace=self.workspace,
            target_path=target_path,
            sandbox_policy=agent.sandbox_policy,
            evidence=self.evidence,
            extra={"project_dir": project_dir or self.workspace},
        )
        self.messages: list[Message] = [Message(Role.SYSTEM, SYSTEM_PROMPT)]
        self._first = True
        self.refused: str | None = None
        self.turns = 0
        self.created_at = time.time()

        if target_path:
            try:
                data = read_target(target_path)
                self.evidence.observed(f"target is {len(data)} bytes", source="intake")
            except ValidationError as exc:
                self.refused = f"target rejected: {exc}"

    def add_user(self, goal: str) -> None:
        """Queue a follow-up user message without running (used before run_turn)."""
        self.messages.append(Message(Role.USER, goal))
        self._first = False

    def run_turn(self, goal: str, on_event=None) -> Job:
        agent = self.agent
        job = Job(goal=goal, target_path=self.target_path)
        job.workspace = self.workspace
        emit = make_emitter(on_event)
        emit({"type": "start", "job_id": job.id, "goal": goal,
              "target": self.target_path, "provider": agent.provider.name})

        if self.refused:
            job.status = "refused"
            job.error = self.refused
            emit({"type": "error", "error": job.error})
            return self._finish(job)

        self.turns += 1
        self.ctx.job_id = job.id
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
        self._loop(job, emit)
        job = self._finish(job)
        artifact = self.ctx.extra.get("modified_path")
        artifact_name = Path(artifact).name if artifact else None
        emit({"type": "final", "status": job.status, "answer": job.final_answer,
              "evidence_summary": self.evidence.summary(), "steps": job.steps,
              "usage": job.usage, "artifact": artifact_name})
        return job

    def _loop(self, job: Job, emit) -> None:
        agent = self.agent
        for step in range(1, agent.max_steps + 1):
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
            _acc_usage(job, resp)

            self.messages.append(Message(
                Role.ASSISTANT, content=resp.content, tool_calls=resp.tool_calls))
            emit({"type": "assistant", "step": step, "content": resp.content,
                  "tool_calls": [{"name": tc.name, "arguments": tc.arguments}
                                 for tc in resp.tool_calls]})

            if not resp.tool_calls:
                job.final_answer = resp.content or ""
                job.status = "completed"
                return

            for tc in resp.tool_calls:
                before = len(self.evidence.all())
                result = agent.mediator.dispatch(tc.name, tc.arguments, self.ctx)
                self.messages.append(Message(
                    Role.TOOL, content=result.content,
                    tool_call_id=tc.id, name=tc.name))
                emit({"type": "tool_result", "step": step, "name": tc.name,
                      "ok": result.ok,
                      "permission": tool_perm(agent.registry, tc.name),
                      "content": (result.content or "")[:4000]})
                for f in self.evidence.all()[before:]:
                    emit({"type": "finding", "tier": f.confidence.label,
                          "claim": f.claim, "source": f.source})

        job.status = "completed"
        job.final_answer = job.final_answer or "(reached step limit without a summary)"

    def _finish(self, job: Job) -> Job:
        job.evidence = self.evidence
        job.audit = self.agent.mediator.audit_log()
        job.transcript = [m.to_openai() for m in self.messages]
        job.finished_at = time.time()
        if job.status == "running":
            job.status = "failed"
        return job


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
        "Investigate it and proceed toward the goal: work on a copy in the "
        "sandbox, verify your work, finish with a clear plain-language summary, "
        "and deliver the final file if you produce one.")


def _acc_usage(job: Job, resp) -> None:
    u = resp.usage
    job.usage["prompt_tokens"] = job.usage.get("prompt_tokens", 0) + u.prompt_tokens
    job.usage["completion_tokens"] = job.usage.get("completion_tokens", 0) + u.completion_tokens
    job.usage["total_tokens"] = job.usage.get("total_tokens", 0) + u.total_tokens
