"""Low-level process runner shared by native backends.

Handles: minimal environment, resource limits via preexec, wall-clock timeout,
whole-process-group kill on timeout, and bounded output capture.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time

from ..security.limits import ResourceLimits
from .result import ExecResult, Isolation


def run_process(
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: str | None,
    timeout: float,
    limits: ResourceLimits,
    max_output: int,
    isolation: Isolation,
    stdin: bytes | None = None,
) -> ExecResult:
    preexec = limits.as_preexec()
    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=cwd,
            preexec_fn=preexec,  # sets rlimits + new session (own process group)
            close_fds=True,
        )
    except (OSError, ValueError) as exc:
        return ExecResult(argv=argv, error=f"spawn failed: {exc}", isolation=isolation)

    timed_out = False
    try:
        out, err = proc.communicate(input=stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc)
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out, err = b"", b""
    duration = time.monotonic() - start

    rc = proc.returncode
    term_signal = None
    exit_code: int | None = rc
    if rc is not None and rc < 0:
        term_signal = -rc
        exit_code = None

    return ExecResult(
        argv=argv,
        exit_code=exit_code,
        term_signal=term_signal,
        timed_out=timed_out,
        stdout=(out or b"")[:max_output],
        stderr=(err or b"")[:max_output],
        duration_s=duration,
        isolation=isolation,
    )


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill the child's whole process group (it ran setsid, so pgid == pid)."""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass
