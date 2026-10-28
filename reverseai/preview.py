"""Find the entry page of a generated website inside a workspace.

A preview is served by the HTTP layer from the conversation workspace. The path
is workspace-relative and must stay inside that workspace. This module is shared
by the agent (to announce a preview in the final event) and the server (to expose
previews for jobs recorded before the field existed).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

ENTRYPOINTS = (
    "index.html", "site/index.html", "public/index.html", "dist/index.html",
    "build/index.html", "app/index.html", "clone/index.html",
)


def preview_entry(workspace: str | Path | None) -> str:
    """Return the first safe entry page in ``workspace``, or an empty string."""
    if not workspace:
        return ""
    root = Path(workspace).resolve()
    for rel in ENTRYPOINTS:
        candidate = (root / rel).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        try:
            if candidate.is_file():
                return rel
        except OSError:
            continue
    return ""


def preview_is_fresh(workspace: str | Path | None, rel: str,
                     since: float) -> bool:
    """True when ``rel`` was written at or after ``since`` (with 1s slack)."""
    if not workspace or not rel:
        return False
    root = Path(workspace).resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
        return path.is_file() and path.stat().st_mtime >= since - 1.0
    except (OSError, ValueError):
        return False


def preview_watch_root(workspace: str | Path | None) -> Path | None:
    """The directory whose files should trigger a live reload."""
    if not workspace:
        return None
    root = Path(workspace).resolve()
    entry = preview_entry(root)
    if entry:
        return (root / Path(entry).parent).resolve()
    return root


def preview_snapshot(workspace: str | Path | None, limit: int = 3000) -> str:
    """A cheap fingerprint of preview files (path, mtime, size)."""
    root = preview_watch_root(workspace)
    if root is None or not root.is_dir():
        return ""
    digest = hashlib.sha1()
    count = 0
    skip = {"node_modules", ".git", "__pycache__", ".venv", "venv"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip)
        for name in sorted(filenames):
            count += 1
            if count > limit:
                return digest.hexdigest() + ":truncated"
            path = Path(dirpath) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                rel = name
            digest.update(f"{rel}\0{stat.st_mtime_ns}\0{stat.st_size}\n".encode())
    return digest.hexdigest()
