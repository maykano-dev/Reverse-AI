"""Tool framework — the controlled interface through which the agent acts.

The reasoning model never touches the host directly. It can only request
operations exposed as Tools, each of which declares a JSON-Schema parameter
spec and a permission tier. The mediator enforces the tier before dispatch.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class Permission(IntEnum):
    """Escalating capability tiers.

    READ      — pure analysis / reading bytes. No side effects.
    EXECUTE   — run code in the sandbox. Contained, but observable behavior.
    WRITE     — produce/modify files in the job workspace (never the original).
    DANGEROUS — anything that could affect the host or escape containment.
    """

    READ = 1
    EXECUTE = 2
    WRITE = 3
    DANGEROUS = 4

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass
class ToolContext:
    """Per-job state handed to every tool invocation."""

    job_id: str
    workspace: str              # writable scratch dir for this job
    target_path: str | None = None
    sandbox_policy: Any = None  # SandboxPolicy; typed Any to avoid import cycle
    evidence: Any = None        # EvidenceLog
    goal: str = ""
    memory: Any = None          # MemoryStore
    sources: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    ok: bool
    content: str                       # model-facing text (goes back to the LLM)
    data: dict[str, Any] = field(default_factory=dict)  # structured, for the job record
    error: str | None = None

    @classmethod
    def success(cls, content: str, **data: Any) -> "ToolResult":
        return cls(ok=True, content=content, data=data)

    @classmethod
    def failure(cls, error: str, content: str | None = None) -> "ToolResult":
        return cls(ok=False, content=content or f"error: {error}", error=error)


class Tool(abc.ABC):
    #: unique tool name exposed to the model (snake_case)
    name: str = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Contain unexpected exceptions at the tool boundary.

        The mediator also contains exceptions, but a tool is a public interface
        and may be called directly by tests or internal code. A partial tool
        call must become a failing ToolResult, not a stack trace or a crash.
        """
        super().__init_subclass__(**kwargs)
        raw = cls.__dict__.get("run")
        if raw is None or getattr(raw, "__tool_contained__", False):
            return

        def contained(self, args, ctx):
            try:
                return raw(self, args, ctx)
            except Exception as exc:  # noqa: BLE001 - interface containment
                return ToolResult.failure(
                    f"{type(exc).__name__}: {exc}",
                    content=f"error: {type(exc).__name__}: {exc}")

        contained.__name__ = getattr(raw, "__name__", "run")
        contained.__tool_contained__ = True  # type: ignore[attr-defined]
        cls.run = contained  # type: ignore[method-assign]
    #: one-line description the model sees
    description: str = ""
    #: JSON Schema (object) describing parameters
    parameters: dict[str, Any] = {"type": "object", "properties": {}}
    #: permission tier required to run this tool
    permission: Permission = Permission.READ

    @abc.abstractmethod
    def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """Execute the tool. Must not raise for ordinary failures — return a
        failing ToolResult instead. May raise only for programmer errors."""

    def spec(self) -> dict[str, Any]:
        """OpenAI/DeepSeek-style function/tool spec."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
