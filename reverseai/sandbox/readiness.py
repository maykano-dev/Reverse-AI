"""Execution readiness preflight.

A target can always be analyzed, but not every target can be *executed* for
behavioral verification. A Linux host can run an ELF of its own architecture
directly; a PE, Mach-O, APK, or foreign-architecture ELF needs an emulator or a
VM. Saying that up front prevents the agent from promising a verified artifact
it cannot produce.

The preflight is deliberately conservative: it reports ``can_verify_natively``
only when the format, architecture, host OS, and an isolating backend all line
up. Emulation is reported separately and requires an explicit rootfs.
"""

from __future__ import annotations

import os
import platform
from dataclasses import asdict, dataclass, field
from typing import Any

from ..core import analyze_file
from ..core.models import AnalysisReport, Arch, BinaryFormat
from .detect import detect_capabilities
from .factory import create_sandbox
from .policy import SandboxPolicy


@dataclass
class ExecutionReadiness:
    target: str
    format: str = "unknown"
    arch: str = "unknown"
    host_os: str = ""
    host_arch: str = ""
    can_analyze: bool = True
    can_verify_natively: bool = False
    can_emulate: bool = False
    can_use_vm: bool = False
    backend: str = ""
    level: int = 0
    verdict: str = "analysis_only"
    reason: str = ""
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_ARCH_ALIASES = {
    "x86_64": {Arch.X86, Arch.X86_64},
    "amd64": {Arch.X86, Arch.X86_64},
    "aarch64": {Arch.ARM, Arch.ARM64},
    "arm64": {Arch.ARM, Arch.ARM64},
    "i386": {Arch.X86},
    "i686": {Arch.X86},
    "riscv64": {Arch.RISCV},
}

_HOST_FORMATS = {
    "linux": {BinaryFormat.ELF},
    "darwin": {BinaryFormat.MACHO},
    "win32": {BinaryFormat.PE},
    "cygwin": {BinaryFormat.PE},
}


def _host_arch_family() -> str:
    machine = platform.machine().lower()
    if machine in ("amd64", "x86_64"):
        return "x86_64"
    if machine in ("arm64", "aarch64"):
        return "aarch64"
    return machine


def _arch_matches(report: AnalysisReport) -> bool:
    family = _host_arch_family()
    allowed = _ARCH_ALIASES.get(family, set())
    if report.arch in (Arch.UNKNOWN,):
        return False
    return report.arch in allowed


def assess_execution(target: str, policy: SandboxPolicy | None = None) -> ExecutionReadiness:
    out = ExecutionReadiness(
        target=target,
        host_os=platform.system().lower(),
        host_arch=_host_arch_family(),
    )
    try:
        report = analyze_file(target)
    except Exception as exc:
        out.can_analyze = False
        out.reason = f"could not analyze the target: {exc}"
        out.suggestions = ["Confirm the file exists and is a supported format."]
        return out

    out.format = report.fmt.value
    out.arch = report.arch.value
    caps = detect_capabilities()
    host_os = out.host_os
    native_format = report.fmt in _HOST_FORMATS.get(host_os, set())
    arch_ok = _arch_matches(report)

    try:
        sandbox = create_sandbox(policy or SandboxPolicy(allow_untrusted_execution=True))
        out.backend = sandbox.name
        out.level = sandbox.isolation_level()
    except Exception as exc:
        out.backend = "unavailable"
        out.reason = f"no isolating sandbox is available: {exc}"
        out.suggestions = [
            "Install bubblewrap and enable unprivileged user namespaces.",
            "Analysis still works; execution-based verification will be refused.",
        ]
        return out

    out.can_verify_natively = bool(native_format and arch_ok and out.level >= 40)
    rootfs = os.environ.get("REVERSEAI_QILING_ROOTFS", "").strip()
    out.can_emulate = bool(caps.qiling and rootfs and os.path.isdir(rootfs))
    from .backends.qemu_backend import QemuVmBackend

    out.can_use_vm = QemuVmBackend.is_available()

    if out.can_verify_natively:
        out.verdict = "executable"
        out.reason = (
            f"{out.format} {out.arch} matches this {host_os}/{out.host_arch} host "
            f"and {out.backend} provides isolation level {out.level}.")
        out.suggestions = ["Proceed with behavioral verification in the sandbox."]
        return out

    if out.can_emulate:
        out.verdict = "emulated"
        out.reason = (
            "The target is not native to this host, but Qiling and "
            "REVERSEAI_QILING_ROOTFS are configured.")
        out.suggestions = ["Use the Qiling backend; confirm the rootfs has the "
                           "target's runtime libraries."]
        return out

    if out.can_use_vm:
        out.verdict = "vm"
        out.reason = (
            "A QEMU kernel/rootfs is configured. The VM surface exists, but a "
            "guest runner must be provided before execution can be certified.")
        out.suggestions = ["Configure the guest runner, then re-run readiness.",
                           "Do not claim behavioral verification from the VM "
                           "surface alone."]
        return out

    out.verdict = "analysis_only"
    if not native_format:
        out.reason = (
            f"{out.format} cannot execute natively on {host_os}. Analysis is "
            "available, but behavioral verification is not.")
    elif not arch_ok:
        out.reason = (
            f"{out.arch} cannot execute natively on this {out.host_arch} host. "
            "Analysis is available, but behavioral verification is not.")
    else:
        out.reason = (
            f"{out.backend} is not isolating enough (level {out.level}); "
            "untrusted execution is refused.")
    out.suggestions = [
        "Analyze the target and report static findings only.",
        "For verification, use a matching host/VM or configure Qiling with a rootfs.",
        "Do not claim a behavioral change was verified when it was not executed.",
    ]
    return out
