"""Human, unique artifact names.

The agent used to hand back files with generic names (``<stem>-modified``) so
several results looked identical in the UI. This module produces descriptive,
collision-free names from the target, the user's goal, and the operation:

    app.exe + "remove the license check" + patch
        -> app-remove-license-check-8f3a1c.exe

Names are safe for headers, filesystems, and downloads. A short random token
keeps repeated operations from overwriting each other.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from pathlib import Path
from typing import Any

_MAX_NAME = 120

_STOP = {
    "a", "an", "the", "and", "or", "but", "to", "of", "in", "on", "for", "with",
    "it", "this", "that", "these", "those", "please", "can", "could", "would",
    "i", "we", "you", "me", "my", "our", "is", "are", "be", "make", "change",
    "want", "need", "so", "then", "from", "into", "as", "at", "by", "about",
}

# Operation -> short, readable word used in the filename.
_OP = {
    "patch": "patched",
    "modify": "modified",
    "rebuild": "rebuilt",
    "clone": "site",
    "site": "site",
    "import": "imports",
    "section": "section",
    "extract": "unpacked",
    "verify": "verified",
    "result": "result",
    "deliver": "result",
}

# Extensions that mark a real file. A hostname like "example.com" must keep its
# full name instead of being reduced to "example".
_FILE_EXTS = {
    ".exe", ".dll", ".sys", ".scr", ".cpl", ".msi", ".bin", ".elf", ".so",
    ".dylib", ".app", ".apk", ".ipa", ".deb", ".rpm", ".zip", ".tar", ".gz",
    ".bz2", ".xz", ".7z", ".rar", ".pdf", ".png", ".jpg", ".jpeg", ".gif",
    ".webp", ".svg", ".wasm", ".o", ".a", ".lib", ".py", ".js", ".ts", ".go",
}


def slug(text: str | None, max_words: int = 6, max_len: int = 48) -> str:
    """Lowercase, hyphen-separated words safe for a filename."""
    if not text:
        return ""
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    words = [w for w in words if w not in _STOP] or words
    out = "-".join(words[:max_words])
    return out[:max_len].strip("-")


def intent_slug(goal: str | None, max_words: int = 6) -> str:
    """The meaningful part of a goal, e.g. 'remove the license check'."""
    # Prefer the imperative clause after common lead-ins.
    text = (goal or "").strip()
    text = re.sub(r"^(please\s+)?(can you\s+|could you\s+|i want you to\s+|i need you to\s+)",
                  "", text, flags=re.IGNORECASE)
    return slug(text, max_words=max_words)


def artifact_name(
    target: str | None = None,
    goal: str | None = None,
    operation: str = "result",
    suffix: str | None = None,
    nonce: str | None = None,
) -> str:
    """Build a descriptive, unique artifact filename.

    ``suffix`` overrides the extension (include the dot, e.g. ``".zip"``).
    ``nonce`` overrides the uniqueness token (mainly for tests).
    """
    if target:
        p = Path(target)
        base = p.stem if p.suffix.lower() in _FILE_EXTS else p.name
    else:
        base = "artifact"
    stem = slug(base, max_words=4, max_len=36) or "artifact"
    op = _OP.get((operation or "result").lower(), slug(operation, 2) or "result")
    intent = intent_slug(goal)
    token = nonce or secrets.token_hex(3)

    parts = [stem, op]
    if intent and intent not in (stem, op):
        parts.append(intent)
    parts.append(token)

    ext = suffix
    if ext is None:
        ext = Path(target).suffix if target else ""
    if ext and not ext.startswith("."):
        ext = "." + ext
    ext = re.sub(r"[^A-Za-z0-9.]", "", ext or "")[:12]

    name = "-".join(p for p in parts if p) + ext
    name = re.sub(r"-{2,}", "-", name)
    return name[:_MAX_NAME]


def safe_download_name(name: str, fallback: str = "artifact") -> str:
    """Strip characters that would break a Content-Disposition header."""
    name = (name or "").replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._-")
    return name[:200] or fallback


def artifact_meta(path: str | Path | None) -> dict[str, Any]:
    """Name, size, sha256, and extension for a delivered file."""
    if not path:
        return {}
    p = Path(path)
    h = hashlib.sha256()
    size = 0
    try:
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                size += len(chunk)
                h.update(chunk)
    except OSError:
        return {"name": p.name, "path": str(p)}
    return {
        "name": safe_download_name(p.name),
        "path": str(p),
        "size": size,
        "sha256": h.hexdigest(),
        "ext": p.suffix.lower().lstrip("."),
    }
