"""QEMU VM backend surface.

A real VM backend needs a kernel, a rootfs, a guest runner, and a way to return
stdout/exit status. This module supplies the command builder and preflight, and
refuses execution until those pieces are configured. It does not pretend that a
QEMU binary alone is a working sandbox.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from ..base import Sandbox, SandboxUnavailable
from ..policy import SandboxPolicy
from ..result import ExecResult, Isolation


@dataclass
class QemuConfig:
    qemu: str = ""
    kernel: str = ""
    rootfs: str = ""
    memory_mb: int = 512
    cpus: int = 2
    append: str = "console=ttyS0 root=/dev/vda rw panic=-1"

    @classmethod
    def from_env(cls) -> "QemuConfig":
        return cls(
            qemu=shutil.which("qemu-system-x86_64") or "",
            kernel=os.environ.get("REVERSEAI_QEMU_KERNEL", ""),
            rootfs=os.environ.get("REVERSEAI_QEMU_ROOTFS", ""),
            memory_mb=int(os.environ.get("REVERSEAI_QEMU_MEMORY_MB", "512") or 512),
            cpus=int(os.environ.get("REVERSEAI_QEMU_CPUS", "2") or 2),
            append=os.environ.get("REVERSEAI_QEMU_APPEND",
                                  "console=ttyS0 root=/dev/vda rw panic=-1"),
        )

    @property
    def configured(self) -> bool:
        return bool(self.qemu and os.path.isfile(self.kernel)
                    and os.path.isfile(self.rootfs))


class QemuVmBackend(Sandbox):
    name = "qemu-vm"

    @classmethod
    def is_available(cls) -> bool:
        return QemuConfig.from_env().configured

    @classmethod
    def isolation_level(cls) -> int:
        return 80

    @classmethod
    def preflight(cls) -> dict:
        cfg = QemuConfig.from_env()
        return {
            "available": cfg.configured,
            "qemu": cfg.qemu,
            "kernel": cfg.kernel,
            "rootfs": cfg.rootfs,
            "memory_mb": cfg.memory_mb,
            "note": ("A configured VM still needs a guest runner to execute an "
                     "argv and return stdout/exit status."),
        }

    @classmethod
    def build_args(cls, argv: list[str] | None = None,
                   config: QemuConfig | None = None) -> list[str]:
        cfg = config or QemuConfig.from_env()
        if not cfg.configured:
            raise SandboxUnavailable("QEMU kernel/rootfs are not configured")
        args = [
            cfg.qemu,
            "-machine", "q35",
            "-m", str(max(128, cfg.memory_mb)),
            "-smp", str(max(1, cfg.cpus)),
            "-kernel", cfg.kernel,
            "-drive", f"file={cfg.rootfs},format=raw,if=virtio",
            "-append", cfg.append,
            "-nographic",
            "-no-reboot",
            "-snapshot",
        ]
        if argv:
            args += ["--", *argv]
        return args

    def run(self, argv, policy: SandboxPolicy, cwd: str | None = None,
            stdin: bytes | None = None) -> ExecResult:
        cfg = QemuConfig.from_env()
        if not cfg.configured:
            raise SandboxUnavailable(
                "QEMU backend is not configured; set REVERSEAI_QEMU_KERNEL and "
                "REVERSEAI_QEMU_ROOTFS")
        raise SandboxUnavailable(
            "the QEMU VM surface is built, but the guest runner contract is not "
            "implemented yet. Refusing to claim a VM execution that would not "
            "return a trustworthy result.")
