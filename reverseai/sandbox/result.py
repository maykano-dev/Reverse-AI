"""Result of a sandboxed execution — includes an honest record of the isolation
that was *actually* applied, so downstream reports never overstate containment.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Isolation:
    """What protections the backend actually enforced for this run."""

    backend: str
    network_blocked: bool = False
    filesystem: str = "host"  # "host" | "readonly" | "namespaced" | "emulated"
    pid_namespace: bool = False
    capabilities_dropped: bool = False
    resource_limited: bool = False
    seccomp: bool = False
    level: int = 0  # 0 = none, higher = stronger (see backend.isolation_level)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExecResult:
    argv: list[str]
    exit_code: int | None = None
    term_signal: int | None = None
    timed_out: bool = False
    stdout: bytes = b""
    stderr: bytes = b""
    duration_s: float = 0.0
    isolation: Isolation | None = None
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None and not self.timed_out and self.exit_code == 0

    def stdout_text(self, errors: str = "replace") -> str:
        return self.stdout.decode("utf-8", errors)

    def stderr_text(self, errors: str = "replace") -> str:
        return self.stderr.decode("utf-8", errors)

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": self.argv,
            "exit_code": self.exit_code,
            "term_signal": self.term_signal,
            "timed_out": self.timed_out,
            "stdout": self.stdout_text(),
            "stderr": self.stderr_text(),
            "duration_s": round(self.duration_s, 4),
            "isolation": self.isolation.to_dict() if self.isolation else None,
            "error": self.error,
            "extra": self.extra,
        }
