"""Bomb-safe archive handling.

A dropped archive may be a decompression bomb (tiny file that expands to
terabytes) or a path-traversal archive (members like ``../../etc/passwd``).
Extracting such a thing naively — even inside a sandbox — can exhaust memory or
disk before limits bite. This module inspects members *before* writing anything
and refuses when totals, counts, ratios, or paths cross safe bounds.

Supports zip and tar (incl. gzip/bzip2/xz-compressed tar). Everything is
checked against caps; nothing is trusted from the archive metadata blindly
(we also cap bytes actually written per member).
"""

from __future__ import annotations

import os
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .validate import safe_join

# Defaults — generous for real software, far below bomb territory.
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024   # 2 GiB expanded
MAX_FILES = 20_000
MAX_RATIO = 200                             # expanded / compressed
MAX_SINGLE_BYTES = 1 * 1024 * 1024 * 1024   # 1 GiB per member


class ArchiveError(Exception):
    pass


class BombDetected(ArchiveError):
    """Archive exceeds safe expansion bounds (likely a decompression bomb)."""


@dataclass
class ExtractResult:
    dest: str
    files: int = 0
    total_bytes: int = 0
    members: list[str] = field(default_factory=list)

    def to_dict(self):
        return {"dest": self.dest, "files": self.files,
                "total_bytes": self.total_bytes,
                "members": self.members[:200]}


def is_archive(data: bytes) -> str | None:
    """Return a format name if ``data`` looks like a supported archive."""
    if data[:4] == b"PK\x03\x04" or data[:4] == b"PK\x05\x06":
        return "zip"
    if data[:2] == b"\x1f\x8b":
        return "gzip"
    if data[:3] == b"BZh":
        return "bzip2"
    if data[:6] == b"\xfd7zXZ\x00":
        return "xz"
    if len(data) > 262 and data[257:262] == b"ustar":
        return "tar"
    if data[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z"
    return None


def safe_extract(
    archive_path: str | os.PathLike,
    dest: str | os.PathLike,
    *,
    max_total: int = MAX_TOTAL_BYTES,
    max_files: int = MAX_FILES,
    max_ratio: int = MAX_RATIO,
    max_single: int = MAX_SINGLE_BYTES,
) -> ExtractResult:
    """Extract ``archive_path`` into ``dest`` with bomb/traversal protection."""
    ap = Path(archive_path)
    dest_p = Path(dest)
    dest_p.mkdir(parents=True, exist_ok=True)
    compressed = ap.stat().st_size or 1

    if zipfile.is_zipfile(ap):
        return _extract_zip(ap, dest_p, compressed, max_total, max_files, max_ratio, max_single)
    try:
        if tarfile.is_tarfile(ap):
            return _extract_tar(ap, dest_p, compressed, max_total, max_files, max_ratio, max_single)
    except (tarfile.TarError, OSError):
        pass
    raise ArchiveError("unsupported or unreadable archive format")


def _guard(total, count, compressed, max_total, max_files, max_ratio):
    if count > max_files:
        raise BombDetected(f"too many members (> {max_files})")
    if total > max_total:
        raise BombDetected(f"expanded size exceeds {max_total} bytes")
    if total > compressed * max_ratio and total > 10 * 1024 * 1024:
        raise BombDetected(f"compression ratio exceeds {max_ratio}x (bomb-like)")


def _extract_zip(ap, dest, compressed, max_total, max_files, max_ratio, max_single):
    res = ExtractResult(dest=str(dest))
    with zipfile.ZipFile(ap) as zf:
        infos = zf.infolist()
        # First pass: declared sizes.
        declared = sum(i.file_size for i in infos)
        _guard(declared, len(infos), compressed, max_total, max_files, max_ratio)
        total = 0
        for info in infos:
            if info.is_dir():
                continue
            if info.file_size > max_single:
                raise BombDetected(f"member {info.filename!r} too large")
            out = safe_join(dest, info.filename)  # refuses traversal
            out.parent.mkdir(parents=True, exist_ok=True)
            # Second pass: cap bytes actually written (defends against lying metadata).
            written = 0
            with zf.open(info) as src, open(out, "wb") as dst:
                while True:
                    chunk = src.read(1024 * 256)
                    if not chunk:
                        break
                    written += len(chunk)
                    total += len(chunk)
                    if written > max_single or total > max_total:
                        dst.close()
                        out.unlink(missing_ok=True)
                        raise BombDetected("actual expanded size exceeded limit mid-extract")
                    dst.write(chunk)
            res.files += 1
            res.members.append(info.filename)
        res.total_bytes = total
    return res


def _extract_tar(ap, dest, compressed, max_total, max_files, max_ratio, max_single):
    res = ExtractResult(dest=str(dest))
    with tarfile.open(ap) as tf:
        members = tf.getmembers()
        declared = sum(m.size for m in members if m.isfile())
        _guard(declared, len(members), compressed, max_total, max_files, max_ratio)
        total = 0
        for m in members:
            if not m.isfile():
                continue
            if m.size > max_single:
                raise BombDetected(f"member {m.name!r} too large")
            out = safe_join(dest, m.name)  # refuses traversal
            out.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(m)
            if src is None:
                continue
            written = 0
            with open(out, "wb") as dst:
                while True:
                    chunk = src.read(1024 * 256)
                    if not chunk:
                        break
                    written += len(chunk)
                    total += len(chunk)
                    if written > max_single or total > max_total:
                        dst.close()
                        out.unlink(missing_ok=True)
                        raise BombDetected("actual expanded size exceeded limit mid-extract")
                    dst.write(chunk)
            res.files += 1
            res.members.append(m.name)
        res.total_bytes = total
    return res
