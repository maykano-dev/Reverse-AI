"""Bubblewrap backend — unprivileged namespace isolation.

This is the primary backend for running potentially-hostile code natively.
It composes a hardened ``bwrap`` invocation:

  * new user/pid/ipc/uts/cgroup namespaces (unprivileged)
  * network namespace with no interfaces unless policy allows network
  * read-only system directories, a fresh tmpfs ``/tmp`` and writable ``/work``
  * a cleared environment, repopulated only from policy.env
  * all capabilities dropped, new session (blocks TIOCSTI injection)
  * ``--die-with-parent`` so nothing outlives the controller

Bubblewrap is the same primitive behind Flatpak and Anthropic's own sandbox
tooling. It requires unprivileged user namespaces to be enabled on the host.
"""

from __future__ import annotations

import os
import shutil
import tempfile

from .._run import run_process
from ..base import Sandbox, SandboxUnavailable
from ..policy import SandboxPolicy
from ..result import ExecResult, Isolation

# System paths bound read-only so dynamic linking and standard tools work.
_SYSTEM_ROBINDS = ["/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/etc/alternatives"]
_SYSTEM_ROBIND_FILES = ["/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/localtime"]


class BubblewrapSandbox(Sandbox):
    name = "bubblewrap"

    @classmethod
    def _bwrap(cls) -> str | None:
        return shutil.which("bwrap")

    @classmethod
    def is_available(cls) -> bool:
        if os.name != "posix" or cls._bwrap() is None:
            return False
        return _userns_available()

    @classmethod
    def isolation_level(cls) -> int:
        return 40

    def run(self, argv, policy: SandboxPolicy, cwd: str | None = None) -> ExecResult:
        bwrap = self._bwrap()
        if bwrap is None:
            raise SandboxUnavailable("bwrap not found")

        workdir = tempfile.mkdtemp(prefix="reverseai-sbx-")
        try:
            bw_args = self._build_args(bwrap, policy, workdir)
            full = bw_args + ["--"] + list(argv)
            isolation = Isolation(
                backend=self.name,
                network_blocked=not policy.allow_network,
                filesystem="namespaced",
                pid_namespace=True,
                capabilities_dropped=policy.drop_capabilities,
                resource_limited=True,
                seccomp=False,
                level=self.isolation_level(),
            )
            result = run_process(
                full,
                # Outer env for the bwrap process itself; bwrap --clearenv then
                # repopulates the child's env from policy.env.
                env={"PATH": "/usr/bin:/bin"},
                cwd=None,  # bwrap controls cwd via --chdir
                timeout=policy.timeout_seconds,
                limits=policy.limits,
                max_output=policy.max_output_bytes,
                isolation=isolation,
            )
            result.extra["workdir"] = workdir
            return result
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _build_args(self, bwrap: str, policy: SandboxPolicy, workdir: str) -> list[str]:
        args = [
            bwrap,
            "--die-with-parent",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--unshare-cgroup-try",
            "--hostname", "sandbox",
            "--clearenv",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
        ]

        if policy.new_session:
            args.append("--new-session")
        if not policy.allow_network:
            args.append("--unshare-net")
        if policy.drop_capabilities:
            args += ["--cap-drop", "ALL"]

        if policy.read_only_system:
            for path in _SYSTEM_ROBINDS:
                if os.path.exists(path):
                    args += ["--ro-bind-try", path, path]
            for path in _SYSTEM_ROBIND_FILES:
                args += ["--ro-bind-try", path, path]

        # Writable working directory. Either a real project dir (coding runs)
        # bound at its own path, or a fresh ephemeral tmpfs-backed scratch dir.
        if policy.workdir and os.path.isdir(policy.workdir):
            real = os.path.realpath(policy.workdir)
            args += ["--bind", real, real, "--chdir", real]
        else:
            args += ["--bind", workdir, "/work", "--chdir", "/work"]

        # Caller-requested read-only exposures (e.g. the target binary).
        for path in policy.ro_binds:
            if os.path.isabs(path) and os.path.exists(path):
                args += ["--ro-bind", path, path]

        # Caller-requested read-write exposures.
        for path in policy.rw_binds:
            if os.path.isabs(path) and os.path.exists(path):
                args += ["--bind", path, path]

        for key, value in policy.env.items():
            args += ["--setenv", key, value]

        return args


def _userns_available() -> bool:
    """Best-effort check that unprivileged user namespaces are usable."""
    # Debian/Ubuntu toggle; absence of the file means "not restricted".
    knob = "/proc/sys/kernel/unprivileged_userns_clone"
    try:
        with open(knob) as fh:
            if fh.read().strip() == "0":
                return False
    except FileNotFoundError:
        pass
    except OSError:
        return False
    max_knob = "/proc/sys/user/max_user_namespaces"
    try:
        with open(max_knob) as fh:
            if int(fh.read().strip() or "0") <= 0:
                return False
    except (FileNotFoundError, ValueError):
        pass
    except OSError:
        return False
    return True
