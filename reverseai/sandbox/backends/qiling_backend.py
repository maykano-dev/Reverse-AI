"""Qiling emulation backend (EXPERIMENTAL).

Qiling emulates PE/ELF/Mach-O across architectures on top of Unicorn, so a
Windows .exe can be executed on a Linux host with no VM — the strongest option
for *foreign-platform* untrusted code because the target's instructions run in
an emulator, never on the real CPU/OS.

Status: experimental and opt-in. It activates only when the `qiling` package is
installed AND a rootfs is configured (REVERSEAI_QILING_ROOTFS), because Qiling
needs platform libraries (e.g. Windows DLLs) to emulate against. Until both are
present, `is_available()` returns False and the factory falls back to namespace
isolation. The orchestration here (timeout, output capture, result mapping) is
unit-tested with a stub; real-emulator behavior depends on the installed Qiling.
"""

from __future__ import annotations

import importlib.util
import os
import time

from ..base import Sandbox, SandboxUnavailable
from ..policy import SandboxPolicy
from ..result import ExecResult, Isolation

ROOTFS_ENV = "REVERSEAI_QILING_ROOTFS"


class QilingSandbox(Sandbox):
    name = "qiling"

    @classmethod
    def _qiling_present(cls) -> bool:
        try:
            return importlib.util.find_spec("qiling") is not None
        except (ImportError, ValueError):
            return False

    @classmethod
    def rootfs(cls) -> str | None:
        root = os.environ.get(ROOTFS_ENV)
        return root if root and os.path.isdir(root) else None

    @classmethod
    def is_available(cls) -> bool:
        return cls._qiling_present() and cls.rootfs() is not None

    @classmethod
    def isolation_level(cls) -> int:
        return 60  # emulation: target code never runs on the host CPU/OS

    def run(self, argv, policy: SandboxPolicy, cwd: str | None = None,
            stdin: bytes | None = None) -> ExecResult:
        rootfs = self.rootfs()
        if not self._qiling_present() or rootfs is None:
            raise SandboxUnavailable(
                f"qiling backend needs the qiling package and {ROOTFS_ENV} set to "
                "a rootfs directory")
        if stdin is not None:
            return ExecResult(
                argv=list(argv),
                error="qiling emulation does not support stdin yet",
                isolation=Isolation(backend=self.name,
                                    network_blocked=not policy.allow_network,
                                    filesystem="emulated", level=self.isolation_level()),
            )

        isolation = Isolation(
            backend=self.name,
            network_blocked=not policy.allow_network,
            filesystem="emulated",
            pid_namespace=False,
            capabilities_dropped=True,
            resource_limited=True,
            seccomp=False,
            level=self.isolation_level(),
        )
        start = time.monotonic()
        try:
            result = self._emulate(list(argv), rootfs, policy, isolation)
        except Exception as exc:  # emulation errors are results, not crashes
            return ExecResult(argv=list(argv), error=f"qiling error: {exc}",
                              isolation=isolation, duration_s=time.monotonic() - start)
        result.duration_s = time.monotonic() - start
        return result

    def _emulate(self, argv, rootfs, policy, isolation) -> ExecResult:
        """Drive Qiling. Isolated into its own method so tests can stub `qiling`."""
        from qiling import Qiling  # type: ignore
        from qiling.const import QL_VERBOSE  # type: ignore

        import io

        stdout = io.BytesIO()
        stderr = io.BytesIO()
        ql = Qiling(argv, rootfs, verbose=QL_VERBOSE.OFF,
                    console=False, stdout=stdout, stderr=stderr)

        timed_out = {"v": False}

        def _watchdog():
            timed_out["v"] = True
            try:
                ql.emu_stop()
            except Exception:
                pass

        import threading

        timer = threading.Timer(policy.timeout_seconds, _watchdog)
        timer.start()
        exit_code: int | None = 0
        try:
            ql.run()
        finally:
            timer.cancel()

        try:
            exit_code = int(getattr(ql.os, "exit_code", 0) or 0)
        except Exception:
            exit_code = None

        return ExecResult(
            argv=argv,
            exit_code=None if timed_out["v"] else exit_code,
            timed_out=timed_out["v"],
            stdout=stdout.getvalue()[:policy.max_output_bytes],
            stderr=stderr.getvalue()[:policy.max_output_bytes],
            isolation=isolation,
        )
