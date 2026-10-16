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
    ) -> None:
        self.provider = provider
        self.registry = registry or self._default_registry(max_permission)
        self.mediator = ToolMediator(self.registry, max_permission=max_permission, confirm=confirm)
        self.max_steps = max_steps
        self.sandbox_policy = sandbox_policy or SandboxPolicy()
        self.temperature = temperature

    @staticmethod
    def _default_registry(max_permission: Permission) -> ToolRegistry:
        reg = ToolRegistry()
        reg.register_all(default_tools())
        # Only expose modification tools when the job may actually write.
        if max_permission >= Permission.WRITE:
            from .modify_tools import modification_tools

            reg.register_all(modification_tools())
        return reg

    def run(self, goal: str, target_path: str | None = None) -> Job:
        job = Job(goal=goal, target_path=target_path)
        job.workspace = tempfile.mkdtemp(prefix=f"reverseai-{job.id}-")
        job.status = "running"
        evidence = EvidenceLog()

        # Validate the target up front; refuse rather than proceed blindly.
        if target_path:
            try:
                data = read_target(target_path)
                evidence.observed(f"target is {len(data)} bytes", source="intake")
            except ValidationError as exc:
                job.status = "refused"
                job.error = f"target rejected: {exc}"
                return self._finish(job, evidence)

        ctx = ToolContext(
            job_id=job.id,
            workspace=job.workspace,
            target_path=target_path,
            sandbox_policy=self.sandbox_policy,
            evidence=evidence,
        )

        messages = [
            Message(Role.SYSTEM, SYSTEM_PROMPT),
            Message(Role.USER, self._initial_user_message(goal, target_path)),
        ]

        for step in range(1, self.max_steps + 1):
            job.steps = step
            resp = self.provider.chat(
                messages,
                tools=self.registry.provider_specs(),
                temperature=self.temperature,
            )
            self._accumulate_usage(job, resp)

            assistant = Message(
                Role.ASSISTANT, content=resp.content, tool_calls=resp.tool_calls
            )
            messages.append(assistant)

            if not resp.tool_calls:
                job.final_answer = resp.content or ""
                job.status = "completed"
                break

            for tc in resp.tool_calls:
                result = self.mediator.dispatch(tc.name, tc.arguments, ctx)
                messages.append(
                    Message(
                        Role.TOOL,
                        content=result.content,
                        tool_call_id=tc.id,
                        name=tc.name,
                    )
                )
        else:
            job.status = "completed"
            job.final_answer = (job.final_answer
                                or "(reached step limit without a final summary)")

        return self._finish(job, evidence, messages)

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
