"""The Agent — reusable configuration that drives conversations.

An Agent bundles the provider, tool registry, policy mediator, and limits. The
actual ReAct loop and all per-dialogue state live in Conversation
(agent/conversation.py): an Agent is the configuration, a Conversation is one
stateful, multi-turn dialogue. ``Agent.run`` is a single-turn convenience.
"""

from __future__ import annotations

from ..sandbox import SandboxPolicy
from .builtins import default_tools
from .context import DEFAULT_MAX_CHARS
from .conversation import Conversation
from .job import Job
from .mediator import ConfirmFn, ToolMediator
from .providers.base import LLMProvider
from .registry import ToolRegistry
from .tools import Permission


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
        template: str = "general",
        memory=None,
        skills: list | None = None,
        delegate_depth: int = 0,
    ) -> None:
        self.provider = provider
        self.max_permission = max_permission
        self.registry = registry or self._default_registry(max_permission, enable_coding)
        self.mediator = ToolMediator(self.registry, max_permission=max_permission, confirm=confirm)
        self.max_steps = max_steps
        self.sandbox_policy = sandbox_policy or SandboxPolicy()
        self.temperature = temperature
        self.max_context_chars = max_context_chars
        self.template = template
        self.memory = memory
        self.skills = skills or []
        self.delegate_depth = delegate_depth

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

    def open(self, target_path: str | None = None,
             project_dir: str | None = None,
             workspace: str | None = None) -> Conversation:
        """Start a stateful conversation (multi-turn). Call run_turn per message."""
        return Conversation(self, target_path=target_path, project_dir=project_dir,
                            workspace=workspace)

    def run(self, goal: str, target_path: str | None = None,
            project_dir: str | None = None, on_event=None,
            workspace: str | None = None) -> Job:
        """Run a single-turn investigation and return the Job.

        ``on_event(dict)`` receives live progress events
        (start/plan/reason/step/assistant/tool_result/source/finding/final/error).
        """
        return self.open(target_path, project_dir, workspace).run_turn(
            goal, on_event=on_event)
