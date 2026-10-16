"""Sandbox backend interface.

A backend knows how to execute an argv under a SandboxPolicy and report what
isolation it achieved. Backends are ranked by ``isolation_level`` so the factory
can pick the strongest one available on the host.
"""

from __future__ import annotations

import abc

from .policy import SandboxPolicy
from .result import ExecResult


class SandboxError(Exception):
    pass


class SandboxUnavailable(SandboxError):
    """Backend cannot run on this host (missing tool / kernel feature)."""


class PolicyViolation(SandboxError):
    """The requested policy cannot be satisfied by this backend."""


class Sandbox(abc.ABC):
    #: human-readable backend id
    name: str = "base"

    @classmethod
    @abc.abstractmethod
    def is_available(cls) -> bool:
        """True if this backend can run on the current host."""

    @classmethod
    @abc.abstractmethod
    def isolation_level(cls) -> int:
        """Relative isolation strength. Higher wins during auto-selection.

        Convention:
          0  = none (runs on host, resource limits only)
          10 = resource-limited subprocess
          40 = OS-namespace isolation (bubblewrap / containers)
          60 = full emulation (qiling) — untrusted code never runs natively
          80 = full-system VM (qemu)
        """

    @abc.abstractmethod
    def run(
        self,
        argv: list[str],
        policy: SandboxPolicy,
        cwd: str | None = None,
    ) -> ExecResult:
        """Execute ``argv`` under ``policy`` and return the result.

        Must never raise on target misbehavior (crash, timeout, nonzero exit) —
        those are reported in the ExecResult. It may raise SandboxError for
        host/config problems.
        """

    def supports_untrusted(self) -> bool:
        """Whether this backend is strong enough to run untrusted code."""
        return self.isolation_level() >= 40
