"""Find the entry page of a generated website inside a workspace.

A preview is served by the HTTP layer from the conversation workspace. The path
is workspace-relative and must stay inside that workspace. This module is shared
by the agent (to announce a preview in the final event) and the server (to expose
previews for jobs recorded before the field existed).
"""

from __future__ import annotations

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
