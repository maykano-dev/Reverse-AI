"""Binary modification engine.

Current strategy: byte-level patching applied to a *copy* of the target, with
provenance (hashes before/after) and optional expected-original assertions so a
patch can never silently hit the wrong bytes. LIEF-backed structural edits
(add imports, sections) load lazily when the library is present.

The original artifact is never mutated in place — every operation writes a new
file into the job workspace.
"""

from .patch import BytePatch, PatchError, PatchResult, apply_byte_patches

__all__ = ["BytePatch", "PatchError", "PatchResult", "apply_byte_patches"]
