"""POSIX resource-limit helpers for confining child processes.

Used by the subprocess sandbox backend as one layer of defense-in-depth
(alongside namespaces, seccomp, and capability dropping). These apply in the
child, after fork, before exec.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    import resource  # POSIX-only
except ImportError:  # pragma: no cover - non-POSIX
    resource = None  # type: ignore[assignment]


@dataclass
class ResourceLimits:
    cpu_seconds: int = 10          # RLIMIT_CPU — hard CPU-time ceiling
    address_space_mb: int = 2048   # RLIMIT_AS — virtual memory
    file_size_mb: int = 64         # RLIMIT_FSIZE — max file a child may write
    open_files: int = 256          # RLIMIT_NOFILE
    # RLIMIT_NPROC is per-UID and system-wide, so it both leaks across unrelated
    # processes and breaks user-namespace creation (clone returns EAGAIN). We
    # leave it unset by default and cap process count via PID namespaces/cgroups
    # instead. Set >0 only for a plain subprocess with no namespace isolation.
    processes: int | None = None   # RLIMIT_NPROC — opt-in
    core_dump: bool = False        # RLIMIT_CORE

    def as_preexec(self):
        """Return a callable suitable for subprocess ``preexec_fn``.

        Runs in the forked child just before exec. Raising here aborts the exec.
        """
        if resource is None:
            return None

        limits = self

        def _apply():  # pragma: no cover - exercised via subprocess, not in-process
            def _set(what, soft, hard=None):
                hard = soft if hard is None else hard
                try:
                    resource.setrlimit(what, (soft, hard))
                except (ValueError, OSError):
                    pass

            _set(resource.RLIMIT_CPU, limits.cpu_seconds)
            _set(resource.RLIMIT_AS, limits.address_space_mb * 1024 * 1024)
            _set(resource.RLIMIT_FSIZE, limits.file_size_mb * 1024 * 1024)
            _set(resource.RLIMIT_NOFILE, limits.open_files)
            if limits.processes and limits.processes > 0 and hasattr(resource, "RLIMIT_NPROC"):
                _set(resource.RLIMIT_NPROC, limits.processes)
            _set(resource.RLIMIT_CORE, 0 if not limits.core_dump else resource.RLIM_INFINITY)
            # New session so we can kill the whole process group on timeout.
            try:
                os.setsid()
            except OSError:
                pass

        return _apply
