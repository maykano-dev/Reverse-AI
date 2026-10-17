"""User-facing text cleanup.

strip_dashes() removes the "AI dash" tell — em/en dashes and hyphenated joins —
and reads them back as natural punctuation, WITHOUT breaking Markdown lists or
code. Applied to everything the model shows a user.
"""

from __future__ import annotations

import re

_LONG_DASHES = "—–‒―−"  # — – ‒ ― −
# A list/ordered marker at the start of a line (kept verbatim).
_MARKER = re.compile(r"^(\s*(?:[-*+]\s+|\d+[.)]\s+))?(.*)$")
# Split on fenced code blocks and inline code so we never touch code.
_CODE_SPLIT = re.compile(r"(```.*?```|`[^`]*`)", re.DOTALL)


def strip_dashes(text: str | None) -> str:
    if not text:
        return text or ""
    parts = _CODE_SPLIT.split(text)
    # Odd indices are code spans/blocks — leave them exactly as-is.
    return "".join(p if i % 2 else _dedash_prose(p) for i, p in enumerate(parts))


def _dedash_prose(s: str) -> str:
    out = []
    for line in s.split("\n"):
        m = _MARKER.match(line)
        marker, body = (m.group(1) or ""), m.group(2)
        # Long dashes -> comma (", "); e.g. "a — b" => "a, b".
        body = re.sub(rf"\s*[{_LONG_DASHES}]\s*", ", ", body)
        # A spaced hyphen used as a dash -> comma.
        body = re.sub(r"\s+-\s+", ", ", body)
        # Hyphen joining two word characters -> space ("general-purpose" => "general purpose").
        body = re.sub(r"(?<=\w)-(?=\w)", " ", body)
        # Tidy up: collapse comma/space runs produced by the above.
        body = re.sub(r"\s*,\s*,", ",", body)
        body = re.sub(r",\s*,", ",", body)
        body = re.sub(r"[ \t]{2,}", " ", body)
        body = re.sub(r"\s+([,.;:!?])", r"\1", body)
        out.append(marker + body)
    return "\n".join(out)
