"""ReverseAI sandbox lab — isolated execution for untrusted binaries.

Secure-by-default execution with backend auto-selection (bubblewrap namespaces,
resource-limited subprocess, and — when installed — qiling emulation / qemu VMs).
"""

from .base import PolicyViolation, Sandbox, SandboxError, SandboxUnavailable
from .detect import Capabilities, detect_capabilities
from .factory import available_backends, create_sandbox, register_backend
from .policy import SandboxPolicy
from .result import ExecResult, Isolation

__all__ = [
    "Sandbox",
    "SandboxError",
    "SandboxUnavailable",
    "PolicyViolation",
    "SandboxPolicy",
    "ExecResult",
    "Isolation",
    "Capabilities",
    "detect_capabilities",
    "create_sandbox",
    "available_backends",
    "register_backend",
]
