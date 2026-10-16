"""Printable-string extraction (ASCII + UTF-16LE), stdlib only."""

from __future__ import annotations

import re


def extract_strings(data: bytes, min_len: int = 4, limit: int | None = None) -> list[str]:
    """Return printable strings found in `data`.

    Captures both ASCII runs and UTF-16LE runs (common in PE binaries).
    `limit` caps the number returned (useful to keep reports bounded).
    """
    out: list[str] = []

    ascii_re = re.compile(rb"[\x20-\x7e]{%d,}" % min_len)
    for m in ascii_re.finditer(data):
        out.append(m.group().decode("ascii", "replace"))
        if limit and len(out) >= limit:
            return out

    utf16_re = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % min_len)
    for m in utf16_re.finditer(data):
        out.append(m.group().decode("utf-16-le", "replace"))
        if limit and len(out) >= limit:
            return out

    return out
