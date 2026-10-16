"""Sandbox policy — the security contract for every execution.

Secure by default: no network, read-only system, tight resource limits, and a
hard refusal to run *untrusted* code unless a backend can actually isolate it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..security.limits import ResourceLimits


@dataclass
class SandboxPolicy:
    # --- isolation ---
    allow_network: bool = False
    read_only_system: bool = True
    drop_capabilities: bool = True
    new_session: bool = True

    # --- trust gate ---
    # Running an unknown/untrusted binary requires this to be explicitly True.
    # The factory then refuses unless an actually-isolating backend is available.
    allow_untrusted_execution: bool = False

    # --- resources ---
    timeout_seconds: float = 10.0
    limits: ResourceLimits = field(default_factory=ResourceLimits)
    max_output_bytes: int = 1 * 1024 * 1024  # cap captured stdout/stderr each

    # --- environment ---
    # Minimal, explicit environment. Never inherits the host env by default.
    env: dict[str, str] = field(
        default_factory=lambda: {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    )

    # Extra host paths to expose read-only inside the sandbox (absolute paths).
    ro_binds: list[str] = field(default_factory=list)
    # Host paths exposed read-WRITE (e.g. a project dir for a build/test run).
    rw_binds: list[str] = field(default_factory=list)
    # If set, bind this dir read-write and chdir into it instead of a fresh
    # tmpfs. Used by the coding tools to operate on a real project.
    workdir: str | None = None

    def trusted_only(self) -> "SandboxPolicy":
        """Return a copy that forbids untrusted execution (for running our own tools)."""
        from dataclasses import replace

        return replace(self, allow_untrusted_execution=False)
