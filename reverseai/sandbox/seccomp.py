"""A small, auditable seccomp-bpf denylist for native Linux targets.

This is defense in depth, not the only boundary. It blocks syscalls that let a
process escape a namespace, inspect another process, load kernel modules, or
open a kernel attack surface. Everything else is allowed, so ordinary programs
continue to work.

Two paths use it:

  * ``install_filter()`` applies the filter to the current process. Used by the
    subprocess backend for trusted commands.
  * ``write_bpf()`` serializes the same cBPF program for bubblewrap's
    ``--seccomp FD`` option, which installs it in the sandboxed child.

Only x86_64 Linux is supported. On any other architecture the helpers report
unavailable and the caller must record ``seccomp=False`` rather than pretend.
"""

from __future__ import annotations

import ctypes
import os
import platform
import struct
import tempfile
from typing import Iterable

AUDIT_ARCH_X86_64 = 0xC000003E

BPF_LD = 0x00
BPF_W = 0x00
BPF_ABS = 0x20
BPF_JMP = 0x05
BPF_JEQ = 0x10
BPF_K = 0x00
BPF_RET = 0x06

SECCOMP_RET_ALLOW = 0x7FFF0000
SECCOMP_RET_ERRNO = 0x00050000
EPERM = 1

PR_SET_NO_NEW_PRIVS = 38
PR_SET_SECCOMP = 22
SECCOMP_MODE_FILTER = 2

# x86_64 syscall numbers. Only syscalls we know how to name are listed.
_SYSCALLS = {
    "getpid": 39,
    "getppid": 110,
    "ptrace": 101,
    "process_vm_readv": 310,
    "process_vm_writev": 311,
    "kcmp": 312,
    "pidfd_getfd": 438,
    "mount": 165,
    "umount2": 166,
    "pivot_root": 155,
    "chroot": 161,
    "move_mount": 429,
    "open_tree": 428,
    "fsopen": 430,
    "fsconfig": 431,
    "fsmount": 432,
    "fspick": 433,
    "mount_setattr": 442,
    "unshare": 272,
    "setns": 308,
    "init_module": 175,
    "finit_module": 313,
    "delete_module": 176,
    "kexec_load": 246,
    "kexec_file_load": 320,
    "reboot": 169,
    "swapon": 167,
    "swapoff": 168,
    "acct": 163,
    "settimeofday": 164,
    "clock_settime": 227,
    "clock_adjtime": 305,
    "adjtimex": 159,
    "add_key": 248,
    "request_key": 249,
    "keyctl": 250,
    "bpf": 321,
    "perf_event_open": 298,
    "userfaultfd": 323,
    "io_uring_setup": 425,
    "io_uring_enter": 426,
    "io_uring_register": 427,
    "open_by_handle_at": 304,
    "name_to_handle_at": 303,
    "personality": 135,
}

DEFAULT_DENY = frozenset(set(_SYSCALLS) - {"getpid", "getppid"})


def available() -> bool:
    return (os.name == "posix" and platform.system().lower() == "linux"
            and platform.machine().lower() in ("x86_64", "amd64"))


def _insn(code: int, jt: int, jf: int, k: int) -> bytes:
    return struct.pack("<HBBI", code, jt, jf, k)


def build_filter(deny: Iterable[str] | None = None) -> bytes:
    """Serialize a cBPF denylist program (raw ``struct sock_filter`` array)."""
    names = set(DEFAULT_DENY if deny is None else deny)
    unknown = names - set(_SYSCALLS)
    if unknown:
        raise ValueError(f"unknown syscalls: {sorted(unknown)}")
    numbers = sorted({_SYSCALLS[n] for n in names})
    # 0 ld arch, 1 jeq arch, 2 ld nr, 3..N jeq, N+1 allow, N+2 kill
    allow_idx = 3 + len(numbers)
    kill_idx = allow_idx + 1
    prog: list[bytes] = []
    prog.append(_insn(BPF_LD | BPF_W | BPF_ABS, 0, 0, 4))
    prog.append(_insn(BPF_JMP | BPF_JEQ | BPF_K, 0, allow_idx - 2,
                      AUDIT_ARCH_X86_64))
    prog.append(_insn(BPF_LD | BPF_W | BPF_ABS, 0, 0, 0))
    for i, nr in enumerate(numbers):
        idx = 3 + i
        prog.append(_insn(BPF_JMP | BPF_JEQ | BPF_K, kill_idx - idx - 1, 0, nr))
    prog.append(_insn(BPF_RET | BPF_K, 0, 0, SECCOMP_RET_ALLOW))
    prog.append(_insn(BPF_RET | BPF_K, 0, 0, SECCOMP_RET_ERRNO | EPERM))
    return b"".join(prog)


class _SockFilter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32)]


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort),
                ("filter", ctypes.POINTER(_SockFilter))]


def install_filter(deny: Iterable[str] | None = None) -> None:
    """Install the filter on the current process. Raises on failure."""
    if not available():
        raise OSError("seccomp filter is only supported on x86_64 Linux")
    raw = build_filter(deny)
    count = len(raw) // 8
    arr = (_SockFilter * count).from_buffer_copy(raw)
    prog = _SockFprog(count, arr)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        err = ctypes.get_errno()
        raise OSError(err, f"prctl(PR_SET_NO_NEW_PRIVS) failed: {os.strerror(err)}")
    if libc.prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER,
                  ctypes.byref(prog), 0, 0) != 0:
        err = ctypes.get_errno()
        raise OSError(err, f"prctl(PR_SET_SECCOMP) failed: {os.strerror(err)}")


def write_bpf(deny: Iterable[str] | None = None) -> tuple[str, int]:
    """Write a compiled filter to a temp file. Returns ``(path, fd)``.

    The caller owns the fd and must close it. The file contains only the raw
    instruction array, which is what bubblewrap's ``--seccomp`` expects.
    """
    fd, path = tempfile.mkstemp(prefix="rvai-seccomp-", suffix=".bpf")
    try:
        os.write(fd, build_filter(deny))
        os.lseek(fd, 0, 0)
    except Exception:
        os.close(fd)
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path, fd


def is_denied(name: str) -> bool:
    return name in _SYSCALLS
