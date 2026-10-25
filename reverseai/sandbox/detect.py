"""Host capability detection for the sandbox lab.

Reports which isolation backends and reverse-engineering emulators are usable,
so the platform can pick the strongest option and tell the user the truth about
how well it can contain untrusted code.
"""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Capabilities:
    bubblewrap: bool = False
    user_namespaces: bool = False
    unshare: bool = False
    docker: bool = False
    podman: bool = False
    qemu_system: bool = False
    qemu_user: bool = False
    # python emulation / analysis libs
    qiling: bool = False
    unicorn: bool = False
    capstone: bool = False
    lief: bool = False
    angr: bool = False
    seccomp: bool = False
    landlock: bool = False
    cgroup_v2: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def best_isolation(self) -> str:
        if self.qiling:
            return "emulation (qiling) — strongest for untrusted native code"
        if self.bubblewrap and self.user_namespaces:
            return "namespace isolation (bubblewrap)"
        if self.docker or self.podman:
            return "container isolation"
        return "none — untrusted execution will be refused"

    def can_run_untrusted(self) -> bool:
        return bool(
            self.qiling
            or (self.bubblewrap and self.user_namespaces)
            or self.docker
            or self.podman
        )


def _lib(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _cgroup_v2() -> bool:
    import os

    try:
        with open("/proc/self/cgroup", "r", encoding="utf-8") as fh:
            return "0::" in fh.read()
    except OSError:
        return False


def _landlock() -> bool:
    """Best-effort: Landlock ABI is exposed by the kernel as a syscall."""
    import os
    import platform

    if platform.system().lower() != "linux" or os.name != "posix":
        return False
    try:
        # landlock_create_ruleset(NULL, 0, LANDLOCK_CREATE_RULESET_VERSION=1)
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        result = libc.syscall(444, None, 0, 1)
        return result > 0
    except Exception:
        return False


def detect_capabilities() -> Capabilities:
    from . import seccomp
    from .backends.bubblewrap import _userns_available

    return Capabilities(
        bubblewrap=shutil.which("bwrap") is not None,
        user_namespaces=_userns_available(),
        unshare=shutil.which("unshare") is not None,
        docker=shutil.which("docker") is not None,
        podman=shutil.which("podman") is not None,
        qemu_system=shutil.which("qemu-system-x86_64") is not None,
        qemu_user=shutil.which("qemu-x86_64") is not None,
        qiling=_lib("qiling"),
        unicorn=_lib("unicorn"),
        capstone=_lib("capstone"),
        lief=_lib("lief"),
        angr=_lib("angr"),
        seccomp=seccomp.available() and (shutil.which("bwrap") is not None),
        landlock=_landlock(),
        cgroup_v2=_cgroup_v2(),
    )
