"""Signed, sandboxed pre/post hooks.

Hooks are operator code, not model output. They are disabled by default and only
run from a signed manifest, in the sandbox, with a bounded environment and
timeout.
"""

from .runner import (
    HookError, HookManifest, HookRegistry, HookResult, HookRunner,
)

__all__ = ["HookManifest", "HookRegistry", "HookRunner", "HookResult", "HookError"]
