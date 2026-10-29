"""Apply a Landlock filesystem policy, then exec the target.

This runs inside bubblewrap. It is intentionally standalone and uses only the
stdlib so it can execute before the target. Paths and the handled-access mask
come from the parent through environment variables.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys

SYS_CREATE_RULESET = 444
SYS_ADD_RULE = 445
SYS_RESTRICT_SELF = 446
RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38

READ = (1 << 0) | (1 << 2)  # execute, read_file
READ_DIR = 1 << 3
WRITE_FILE = 1 << 1
TRUNCATE = 1 << 14


class RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class PathBeneathAttr(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64),
                ("parent_fd", ctypes.c_int32)]


def _fail(message: str) -> None:
    print(f"landlock: {message}", file=sys.stderr)
    raise SystemExit(125)


def _paths(name: str) -> list[str]:
    return [p for p in (os.environ.get(name, "").split(os.pathsep)) if p]


def main() -> None:
    if platform.system().lower() != "linux":
        _fail("not Linux")
    try:
        handled = int(os.environ.get("REVERSEAI_LANDLOCK_HANDLED", "0") or 0)
    except ValueError:
        _fail("bad handled mask")
    if not handled:
        _fail("empty handled mask")
    libc = ctypes.CDLL(None, use_errno=True)
    attr = RulesetAttr(handled)
    fd = libc.syscall(SYS_CREATE_RULESET, ctypes.byref(attr),
                      ctypes.sizeof(attr), 0)
    if fd < 0:
        _fail(f"create_ruleset: errno {ctypes.get_errno()}")

    def add(path: str, allowed: int) -> None:
        if not path or not os.path.exists(path):
            return
        try:
            pfd = os.open(path, os.O_PATH | os.O_CLOEXEC)
        except OSError:
            return
        try:
            pb = PathBeneathAttr(allowed, pfd)
            rc = libc.syscall(SYS_ADD_RULE, fd, RULE_PATH_BENEATH,
                              ctypes.byref(pb), 0)
            if rc < 0:
                _fail(f"add_rule {path}: errno {ctypes.get_errno()}")
        finally:
            os.close(pfd)

    def _file_mask(path: str, base: int) -> int:
        if os.path.isdir(path):
            return base
        return base & (READ | WRITE_FILE | TRUNCATE)

    for path in _paths("REVERSEAI_LANDLOCK_READ"):
        allowed = handled & READ
        if os.path.isdir(path):
            allowed |= handled & READ_DIR
        add(path, _file_mask(path, allowed))
    for path in _paths("REVERSEAI_LANDLOCK_WRITE"):
        add(path, _file_mask(path, handled))
    if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        _fail(f"no_new_privs: errno {ctypes.get_errno()}")
    if libc.syscall(SYS_RESTRICT_SELF, fd, 0) < 0:
        _fail(f"restrict_self: errno {ctypes.get_errno()}")
    os.close(fd)
    argv = sys.argv[1:]
    if not argv:
        _fail("no target command")
    try:
        os.execvpe(argv[0], argv, os.environ)
    except OSError as exc:
        _fail(f"exec {argv[0]}: {exc}")


if __name__ == "__main__":
    main()
