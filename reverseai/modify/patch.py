"""Byte-level patching — applied to a copy, with provenance and safety checks."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..security.validate import ValidationError, read_target, safe_join


class PatchError(Exception):
    pass


@dataclass
class BytePatch:
    offset: int
    data: bytes
    #: if set, the bytes currently at ``offset`` must equal this, or we refuse.
    expected_original: bytes | None = None

    def __post_init__(self) -> None:
        if self.offset < 0:
            raise PatchError("patch offset must be non-negative")
        if not self.data:
            raise PatchError("patch data must be non-empty")
        if self.expected_original is not None and len(self.expected_original) != len(self.data):
            raise PatchError("expected_original length must match data length")


@dataclass
class PatchResult:
    output_path: str
    original_sha256: str
    modified_sha256: str
    patches_applied: int
    bytes_changed: int
    details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_path": self.output_path,
            "original_sha256": self.original_sha256,
            "modified_sha256": self.modified_sha256,
            "patches_applied": self.patches_applied,
            "bytes_changed": self.bytes_changed,
            "details": self.details,
        }


def apply_byte_patches(
    src_path: str | Path,
    patches: list[BytePatch],
    out_dir: str | Path,
    out_name: str | None = None,
) -> PatchResult:
    """Apply ``patches`` to a copy of ``src_path`` written under ``out_dir``.

    Validates every patch is in bounds and (when provided) that the existing
    bytes match ``expected_original``. The original file is never modified.
    """
    if not patches:
        raise PatchError("no patches supplied")

    data = read_target(src_path)
    original_sha = hashlib.sha256(data).hexdigest()
    buf = bytearray(data)
    size = len(buf)

    details: list[dict[str, Any]] = []
    changed = 0
    for i, p in enumerate(patches):
        end = p.offset + len(p.data)
        if end > size:
            raise PatchError(
                f"patch {i} out of bounds: offset {p.offset}+{len(p.data)} > size {size}"
            )
        current = bytes(buf[p.offset:end])
        if p.expected_original is not None and current != p.expected_original:
            raise PatchError(
                f"patch {i} expected {p.expected_original.hex()} at {p.offset:#x} "
                f"but found {current.hex()}"
            )
        buf[p.offset:end] = p.data
        changed += sum(1 for a, b in zip(current, p.data) if a != b)
        details.append({
            "index": i,
            "offset": p.offset,
            "length": len(p.data),
            "from": current.hex(),
            "to": p.data.hex(),
        })

    name = out_name or (Path(src_path).name + ".patched")
    out_path = safe_join(out_dir, name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(buf))

    # Preserve the source's executable bits so the modified copy stays runnable,
    # but never carry over setuid/setgid/sticky bits.
    try:
        src_mode = os.stat(src_path).st_mode
        safe_mode = stat.S_IMODE(src_mode) & ~(stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX)
        os.chmod(out_path, safe_mode)
    except OSError:
        pass

    return PatchResult(
        output_path=str(out_path),
        original_sha256=original_sha,
        modified_sha256=hashlib.sha256(bytes(buf)).hexdigest(),
        patches_applied=len(patches),
        bytes_changed=changed,
        details=details,
    )
