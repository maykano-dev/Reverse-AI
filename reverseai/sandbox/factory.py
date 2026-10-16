"""Select and construct the strongest sandbox backend available.

Policy drives the choice. Crucially, if the policy allows *untrusted* execution
but no backend can actually isolate it, we refuse rather than silently running
hostile code on the host.
"""

from __future__ import annotations

from .backends.bubblewrap import BubblewrapSandbox
from .backends.qiling_backend import QilingSandbox
from .backends.subprocess_backend import SubprocessSandbox
from .base import Sandbox, SandboxUnavailable
from .policy import SandboxPolicy

# Registered backends. Ordered by isolation strength at selection time.
# Emulation (qiling) outranks namespaces for untrusted *foreign-platform* code;
# it is only "available" when installed and configured, so it stays dormant
# otherwise.
_BACKENDS: list[type[Sandbox]] = [
    QilingSandbox,
    BubblewrapSandbox,
    SubprocessSandbox,
]


def available_backends() -> list[type[Sandbox]]:
    return [b for b in _BACKENDS if b.is_available()]


def register_backend(backend: type[Sandbox]) -> None:
    """Register an additional backend, keeping the list ordered by isolation."""
    if backend not in _BACKENDS:
        _BACKENDS.append(backend)
        _BACKENDS.sort(key=lambda b: b.isolation_level(), reverse=True)


def create_sandbox(policy: SandboxPolicy) -> Sandbox:
    """Return the strongest available backend that satisfies ``policy``.

    Raises SandboxUnavailable if untrusted execution is requested but nothing on
    this host can contain it.
    """
    candidates = sorted(
        available_backends(), key=lambda b: b.isolation_level(), reverse=True
    )
    if not candidates:
        raise SandboxUnavailable("no sandbox backend available on this host")

    if policy.allow_untrusted_execution:
        for backend in candidates:
            if backend().supports_untrusted():
                return backend()
        raise SandboxUnavailable(
            "untrusted execution requested but no isolating backend is available "
            "(need bubblewrap + user namespaces, a container runtime, or qiling). "
            "Refusing to run untrusted code on the host."
        )

    # Trusted command: still prefer the strongest backend.
    return candidates[0]()
