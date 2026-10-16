"""Input validation and safe filesystem helpers.

Everything the platform ingests is untrusted. These helpers enforce the
boundaries so no other layer has to re-derive them: size caps, path
containment (no traversal / symlink escape), and safe archive handling.
"""

from __future__ import annotations

import os
from pathlib import Path

# Hard ceilings. A single analysis target should never be arbitrarily large.
MAX_FILE_BYTES = 512 * 1024 * 1024  # 512 MiB
MAX_PATH_LEN = 4096


class ValidationError(Exception):
    """Raised when untrusted input violates a safety boundary."""


def validate_file_size(size: int, limit: int = MAX_FILE_BYTES) -> None:
    if size < 0:
        raise ValidationError("negative file size")
    if size > limit:
        raise ValidationError(f"file too large: {size} bytes > limit {limit}")


def read_target(path: str | os.PathLike, limit: int = MAX_FILE_BYTES) -> bytes:
    """Read a target file with a hard size cap, following no symlinks on the final component.

    Reads at most ``limit + 1`` bytes to detect oversize without loading a huge
    file into memory.
    """
    p = Path(path)
    if len(str(p)) > MAX_PATH_LEN:
        raise ValidationError("path too long")
    if not p.exists():
        raise ValidationError(f"no such file: {p}")
    if p.is_symlink():
        raise ValidationError(f"refusing to read symlink: {p}")
    if not p.is_file():
        raise ValidationError(f"not a regular file: {p}")

    size = p.stat().st_size
    validate_file_size(size, limit)

    with open(p, "rb") as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise ValidationError(f"file exceeded size limit while reading: >{limit} bytes")
    return data


def contains_path(root: str | os.PathLike, candidate: str | os.PathLike) -> bool:
    """True iff ``candidate`` resolves to a location inside ``root`` (no escape).

    Resolves symlinks on both sides. Use before writing any path derived from
    untrusted input (e.g. archive member names).
    """
    root_r = Path(root).resolve()
    cand_r = Path(candidate).resolve()
    try:
        cand_r.relative_to(root_r)
        return True
    except ValueError:
        return False


def safe_join(root: str | os.PathLike, *parts: str) -> Path:
    """Join under ``root`` and guarantee the result stays within ``root``.

    Rejects absolute components and any ``..`` traversal that escapes root.
    """
    root_p = Path(root)
    joined = root_p
    for part in parts:
        if os.path.isabs(part):
            raise ValidationError(f"absolute path component not allowed: {part!r}")
        joined = joined / part
    # Resolve without requiring existence, then confirm containment.
    root_r = root_p.resolve()
    joined_r = (root_r / Path(*parts)).resolve() if parts else root_r
    try:
        joined_r.relative_to(root_r)
    except ValueError:
        raise ValidationError(f"path escapes root: {joined_r} not under {root_r}")
    return joined_r
