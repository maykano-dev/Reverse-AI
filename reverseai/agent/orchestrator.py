"""The agent loop — ReAct-style tool use driving an investigation to a result.

Flow per step:
  1. ask the provider for the next action given the conversation + tool specs
  2. if it requests tool calls, run each through the mediator (policy-enforced,
     exception-contained) and feed results back
  3. if it replies with prose and no tool calls, that is the final answer

Everything is captured in a Job: transcript, audit log, evidence, usage.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

from ..sandbox import SandboxPolicy
from ..security.validate import ValidationError, read_target
from .builtins import default_tools
from .context import DEFAULT_MAX_CHARS, compact_messages
from .evidence import EvidenceLog
from .job import Job
from .mediator import ConfirmFn, ToolMediator
from .prompts import SYSTEM_PROMPT
from .providers.base import LLMProvider, Message, Role
from .registry import ToolRegistry
from .tools import Permission, ToolContext


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry | None = None,
        max_permission: Permission = Permission.EXECUTE,
        max_steps: int = 24,
        sandbox_policy: SandboxPolicy | None = None,
        confirm: ConfirmFn | None = None,
        temperature: float = 0.0,
        enable_coding: bool = True,
        max_context_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        self.provider = provider
        self.registry = registry or self._default_registry(max_permission, enable_coding)
        self.mediator = ToolMediator(self.registry, max_permission=max_permission, confirm=confirm)
        self.max_steps = max_steps
        self.sandbox_policy = sandbox_policy or SandboxPolicy()
        self.temperature = temperature
        self.max_context_chars = max_context_chars

    @staticmethod
    def _default_registry(max_permission: Permission, enable_coding: bool = True) -> ToolRegistry:
        reg = ToolRegistry()
        reg.register_all(default_tools())
        # Only expose modification tools when the job may actually write.
        if max_permission >= Permission.WRITE:
            from .modify_tools import modification_tools

            reg.register_all(modification_tools())
        if enable_coding:
            from .coding_tools import coding_tools

            reg.register_all(coding_tools())
        return reg

    def run(self, goal: str, target_path: str | None = None,
            project_dir: str | None = None, on_event=None) -> Job:
        """Run an investigation. ``on_event(dict)`` receives live progress events
        (start/step/assistant/tool_result/finding/final/error) as they occur."""
        job = Job(goal=goal, target_path=target_path)
        job.workspace = tempfile.mkdtemp(prefix=f"reverseai-{job.id}-")
        job.status = "running"
        evidence = EvidenceLog()
        emit = _make_emitter(on_event)
        emit({"type": "start", "job_id": job.id, "goal": goal,
              "target": target_path, "provider": self.provider.name})

        # Validate the target up front; refuse rather than proceed blindly.
        if target_path:
            try:
                data = read_target(target_path)
                evidence.observed(f"target is {len(data)} bytes", source="intake")
            except ValidationError as exc:
                job.status = "refused"
                job.error = f"target rejected: {exc}"
                emit({"type": "error", "error": job.error})
                return self._finish(job, evidence)

        ctx = ToolContext(
            job_id=job.id,
            workspace=job.workspace,
            target_path=target_path,
            sandbox_policy=self.sandbox_policy,
            evidence=evidence,
            extra={"project_dir": project_dir or job.workspace},
        )

        messages = [
            Message(Role.SYSTEM, SYSTEM_PROMPT),
            Message(Role.USER, self._initial_user_message(goal, target_path)),
        ]

        for step in range(1, self.max_steps + 1):
            job.steps = step
            emit({"type": "step", "step": step})
            messages = compact_messages(messages, self.max_context_chars)
            try:
                resp = self.provider.chat(
                    messages,
                    tools=self.registry.provider_specs(),
                    temperature=self.temperature,
                )
            except Exception as exc:
                job.status = "failed"
                job.error = f"provider error: {exc}"
                emit({"type": "error", "error": job.error})
                return self._finish(job, evidence, messages)
            self._accumulate_usage(job, resp)

            assistant = Message(
                Role.ASSISTANT, content=resp.content, tool_calls=resp.tool_calls
            )
            messages.append(assistant)
            emit({"type": "assistant", "step": step, "content": resp.content,
                  "tool_calls": [{"name": tc.name, "arguments": tc.arguments}
                                 for tc in resp.tool_calls]})

            if not resp.tool_calls:
                job.final_answer = resp.content or ""
                job.status = "completed"
                break

            for tc in resp.tool_calls:
                before = len(evidence.all())
                result = self.mediator.dispatch(tc.name, tc.arguments, ctx)
                messages.append(
                    Message(
                        Role.TOOL,
                        content=result.content,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )
                emit({"type": "tool_result", "step": step, "name": tc.name,
                      "ok": result.ok,
                      "permission": _tool_perm(self.registry, tc.name),
                      "content": (result.content or "")[:4000]})
                for f in evidence.all()[before:]:
                    emit({"type": "finding", "tier": f.confidence.label,
                          "claim": f.claim, "source": f.source})
        else:
            job.status = "completed"
            job.final_answer = (job.final_answer
                                or "(reached step limit without a final summary)")

        job = self._finish(job, evidence, messages)
        emit({"type": "final", "status": job.status, "answer": job.final_answer,
              "evidence_summary": evidence.summary(), "steps": job.steps,
              "usage": job.usage})
        return job

    def _finish(self, job: Job, evidence: EvidenceLog, messages=None) -> Job:
        import time

        job.evidence = evidence
        job.audit = self.mediator.audit_log()
        if messages is not None:
            job.transcript = [m.to_openai() for m in messages]
        job.finished_at = time.time()
        if job.status == "running":
            job.status = "failed"
        return job

    @staticmethod
    def _initial_user_message(goal: str, target_path: str | None) -> str:
        parts = [f"Goal:\n{goal}"]
        if target_path:
            parts.append(f"\nTarget file: {Path(target_path).name} (path: {target_path})")
        parts.append(
            "\nBegin by assessing host capabilities and analyzing the target, "
            "then proceed toward the goal. Record findings at the correct "
            "confidence tier and finish with an honest summary."
        )
        return "\n".join(parts)

    @staticmethod
    def _accumulate_usage(job: Job, resp) -> None:
        u = resp.usage
        job.usage["prompt_tokens"] = job.usage.get("prompt_tokens", 0) + u.prompt_tokens
        job.usage["completion_tokens"] = (
            job.usage.get("completion_tokens", 0) + u.completion_tokens
        )
        job.usage["total_tokens"] = job.usage.get("total_tokens", 0) + u.total_tokens


def _tool_perm(registry, name: str) -> str:
    tool = registry.get(name)
    return tool.permission.label if tool else "unknown"


def _make_emitter(on_event):
    """Wrap on_event so a bad callback can never break the agent loop."""
    if on_event is None:
        return lambda _e: None

    def _emit(event):
        try:
            on_event(event)
        except Exception:
            pass

    return _emit
