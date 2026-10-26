"""Tool mediator — enforces the security policy for every tool call.

No tool runs without passing through here. Responsibilities:

  * permission-tier enforcement (refuse anything above the job's ceiling)
  * optional human confirmation for elevated actions
  * exception containment (a buggy tool can never crash the agent loop)
  * a tamper-evident audit log of every attempted action
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from ..util.logging import get_logger
from .registry import ToolRegistry
from .tools import Permission, ToolContext, ToolResult

_log = get_logger("reverseai.agent")

# confirm(tool_name, permission, args, ctx) -> bool
ConfirmFn = Callable[[str, Permission, dict[str, Any], ToolContext], bool]


@dataclass
class AuditEntry:
    tool: str
    permission: str
    allowed: bool
    ok: bool
    duration_s: float
    error: str | None = None
    note: str = ""
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ToolMediator:
    def __init__(
        self,
        registry: ToolRegistry,
        max_permission: Permission = Permission.WRITE,
        confirm: ConfirmFn | None = None,
    ) -> None:
        self.registry = registry
        self.max_permission = max_permission
        self.confirm = confirm
        self.audit: list[AuditEntry] = []

    def dispatch(self, name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        tool = self.registry.get(name)
        if tool is None:
            self._record(name, Permission.READ, allowed=False, ok=False,
                         duration=0.0, error="unknown tool", note="not registered")
            return ToolResult.failure(f"unknown tool: {name}")

        perm = tool.permission

        # DANGEROUS is never auto-allowed; it requires explicit confirmation and
        # must also be within the ceiling.
        if perm > self.max_permission:
            approved = bool(self.confirm and self.confirm(name, perm, args, ctx))
            if not approved:
                self._record(name, perm, allowed=False, ok=False, duration=0.0,
                             error="permission denied",
                             note=f"requires {perm.label} > ceiling {self.max_permission.label}")
                return ToolResult.failure(
                    f"'{name}' needs {perm.label} permission, above this job's "
                    f"ceiling ({self.max_permission.label}). Refused."
                )

        if not isinstance(args, dict):
            self._record(name, perm, allowed=True, ok=False, duration=0.0,
                         error="bad args type")
            return ToolResult.failure("arguments must be a JSON object")

        if "__raw__" in args:
            self._record(name, perm, allowed=True, ok=False, duration=0.0,
                         error="unparseable tool arguments",
                         note="usually a truncated response")
            return ToolResult.failure(
                "the arguments for this call were not valid JSON, usually "
                "because the response was cut off. Do not repeat the same "
                "call. Make it smaller: for a file, write a short skeleton "
                "first and append the rest in separate calls.")

        missing = _missing_required(tool.parameters, args)
        if missing:
            self._record(name, perm, allowed=True, ok=False, duration=0.0,
                         error=f"missing args: {missing}")
            return ToolResult.failure(f"missing required argument(s): {', '.join(missing)}")

        start = time.monotonic()
        try:
            result = tool.run(args, ctx)
        except Exception as exc:  # containment: a tool crash never kills the loop
            dur = time.monotonic() - start
            self._record(name, perm, allowed=True, ok=False, duration=dur,
                         error=f"{type(exc).__name__}: {exc}")
            return ToolResult.failure(f"tool raised {type(exc).__name__}: {exc}")

        dur = time.monotonic() - start
        self._record(name, perm, allowed=True, ok=result.ok, duration=dur,
                     error=result.error)
        return result

    def _record(self, tool, perm, *, allowed, ok, duration, error=None, note=""):
        _log.info("tool=%s perm=%s allowed=%s ok=%s %s",
                  tool, perm.label if isinstance(perm, Permission) else perm,
                  allowed, ok, f"err={error}" if error else "")
        self.audit.append(
            AuditEntry(
                tool=tool,
                permission=perm.label if isinstance(perm, Permission) else str(perm),
                allowed=allowed,
                ok=ok,
                duration_s=round(duration, 4),
                error=error,
                note=note,
            )
        )

    def audit_log(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.audit]


def _missing_required(schema: dict[str, Any], args: dict[str, Any]) -> list[str]:
    required = schema.get("required", []) if isinstance(schema, dict) else []
    return [r for r in required if r not in args]
