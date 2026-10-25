"""Landlock capability surface.

This module reports the kernel ABI and builds a human-readable ruleset plan. It
does **not** claim enforcement: the bubblewrap backend remains the filesystem
boundary. A future backend can apply the plan in the child before exec.
"""

from __future__ import annotations

import ctypes
import os
import platform
from dataclasses import asdict, dataclass, field
from typing import Any

SYS_LANDLOCK_CREATE_RULESET = 444
LANDLOCK_CREATE_RULESET_VERSION = 1

ACCESS_FS = {
    "execute": 1 << 0,
    "write_file": 1 << 1,
    "read_file": 1 << 2,
    "read_dir": 1 << 3,
    "remove_dir": 1 << 4,
    "remove_file": 1 << 5,
    "make_char": 1 << 6,
    "make_dir": 1 << 7,
    "make_reg": 1 << 8,
    "make_sock": 1 << 9,
    "make_fifo": 1 << 10,
    "make_block": 1 << 11,
    "make_sym": 1 << 12,
    "refer": 1 << 13,
    "truncate": 1 << 14,
    "ioctl_dev": 1 << 15,
}


def abi_version() -> int:
    if os.name != "posix" or platform.system().lower() != "linux":
        return 0
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        result = libc.syscall(SYS_LANDLOCK_CREATE_RULESET, None, 0,
                              LANDLOCK_CREATE_RULESET_VERSION)
        return int(result) if result > 0 else 0
    except Exception:
        return 0


def available() -> bool:
    return abi_version() > 0


@dataclass
class RulesetPlan:
    abi: int
    handled_access: int
    read_paths: list[str] = field(default_factory=list)
    write_paths: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan(read_paths: list[str], write_paths: list[str] | None = None) -> RulesetPlan:
    """Build a ruleset plan; applying it is a backend responsibility."""
    abi = abi_version()
    if abi <= 0:
        return RulesetPlan(0, 0, [], [], "Landlock is not available on this kernel")
    handled = 0
    # ABI 1 has the original filesystem rights; later ABI versions add bits.
    for name in ("execute", "write_file", "read_file", "read_dir",
                 "remove_dir", "remove_file", "make_char", "make_dir",
                 "make_reg", "make_sock", "make_fifo", "make_block", "make_sym"):
        handled |= ACCESS_FS[name]
    if abi >= 2:
        handled |= ACCESS_FS["refer"]
    if abi >= 3:
        handled |= ACCESS_FS["truncate"]
    if abi >= 5:
        handled |= ACCESS_FS["ioctl_dev"]
    return RulesetPlan(
        abi, handled, list(read_paths), list(write_paths or []),
        "Plan only. The bubblewrap mount namespace remains the enforced "
        "filesystem boundary in this release.")
