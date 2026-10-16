"""Minimal .env loader (no dependency).

Reads KEY=VALUE lines from a .env file and sets them in the process environment
*without* overriding variables that are already set. Keeps secrets out of code
and lets `python -m reverseai serve` pick up the model key from a local file.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: str | os.PathLike | None = None, *, override: bool = False) -> int:
    """Load variables from ``path`` (default: ./.env). Returns how many were set."""
    p = Path(path) if path else Path.cwd() / ".env"
    if not p.is_file():
        return 0
    count = 0
    try:
        for raw in p.read_text("utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key:
                continue
            if override or key not in os.environ:
                os.environ[key] = value
                count += 1
    except OSError:
        return count
    return count
