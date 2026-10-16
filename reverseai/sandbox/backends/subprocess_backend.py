"""Baseline backend: a resource-limited subprocess.

Isolation: RLIMIT ceilings (CPU/memory/file-size/procs), a minimal environment,
and whole-process-group kill on timeout. It does NOT isolate the network or
filesystem, so it is only ever used for *trusted* commands (our own analysis
tools). It is never selected to run untrusted targets.
"""

from __future__ import annotations

import os

from .._run import run_process
from ..base import Sandbox
from ..policy import SandboxPolicy
from ..result import ExecResult, Isolation


class SubprocessSandbox(Sandbox):
    name = "subprocess"

    @classmethod
    def is_available(cls) -> bool:
        return os.name == "posix"

    @classmethod
    def isolation_level(cls) -> int:
        return 10

    def run(self, argv, policy: SandboxPolicy, cwd: str | None = None) -> ExecResult:
        isolation = Isolation(
            backend=self.name,
            network_blocked=False,
            filesystem="host",
            pid_namespace=False,
            capabilities_dropped=False,
            resource_limited=True,
            seccomp=False,
            level=self.isolation_level(),
        )
        return run_process(
            list(argv),
            env=dict(policy.env),
            cwd=cwd,
            timeout=policy.timeout_seconds,
            limits=policy.limits,
            max_output=policy.max_output_bytes,
            isolation=isolation,
        )
