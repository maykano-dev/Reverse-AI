"""Persistent project workbook - so the agent keeps its focus on the goal.

When ReverseAI works in a real folder on the user's machine, it keeps a small,
durable workbook in that folder under ``.reverseai/``:

- ``plan.json`` - structured state: the goal, a next-steps checklist, and notes.
- ``PROJECT.md`` - the same thing, human-readable, so the user can see and edit it.

The workbook is loaded into the agent's context at the start of every turn
(``project_state_block``), which is what keeps a long, multi-turn build on
track instead of drifting. The agent maintains it with the ``update_project_plan``
tool as work progresses; the user can also just edit ``PROJECT.md``.

This is the project analogue of long-term memory: memory is cross-project facts;
the workbook is this project's goal and plan.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DIR = ".reverseai"
_PLAN = "plan.json"
_MD = "PROJECT.md"
_MAX_STEPS = 40
_MAX_NOTES = 30
# Folders that mean "not empty, but nothing of the user's yet".
_IGNORE = {".reverseai", ".git", ".hg", ".svn", "__pycache__", ".DS_Store",
           ".idea", ".vscode", "node_modules", ".venv", "venv"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _base(project_dir: str | Path) -> Path:
    return Path(project_dir).resolve()


def _plan_path(project_dir: str | Path) -> Path:
    return _base(project_dir) / _DIR / _PLAN


def load_plan(project_dir: str | Path) -> dict[str, Any]:
    """Return the stored plan, or an empty skeleton if none exists."""
    p = _plan_path(project_dir)
    if p.is_file():
        try:
            data = json.loads(p.read_text("utf-8"))
            if isinstance(data, dict):
                data.setdefault("goal", "")
                data.setdefault("steps", [])
                data.setdefault("notes", [])
                return data
        except (OSError, ValueError):
            pass
    return {"goal": "", "steps": [], "notes": [], "updated": ""}


def has_plan(project_dir: str | Path) -> bool:
    return _plan_path(project_dir).is_file()


def save_plan(project_dir: str | Path, plan: dict[str, Any]) -> None:
    base = _base(project_dir)
    d = base / _DIR
    d.mkdir(parents=True, exist_ok=True)
    plan = dict(plan)
    plan["updated"] = _now()
    plan["steps"] = [_norm_step(s) for s in plan.get("steps", [])][:_MAX_STEPS]
    plan["notes"] = [str(n) for n in plan.get("notes", [])][-_MAX_NOTES:]
    (d / _PLAN).write_text(json.dumps(plan, ensure_ascii=False, indent=2), "utf-8")
    try:
        (base / _DIR / _MD).write_text(render_markdown(plan, base.name), "utf-8")
    except OSError:
        pass


def _norm_step(s: Any) -> dict[str, Any]:
    if isinstance(s, dict):
        return {"text": str(s.get("text", "")).strip(), "done": bool(s.get("done"))}
    return {"text": str(s).strip(), "done": False}


def update_plan(project_dir: str | Path, *, goal: str | None = None,
                add_steps: list[str] | None = None,
                complete: list | None = None,
                replace_steps: list[str] | None = None,
                notes: str | list[str] | None = None) -> dict[str, Any]:
    """Apply an incremental change to the workbook and persist it."""
    plan = load_plan(project_dir)
    if goal is not None:
        plan["goal"] = str(goal).strip()
    if replace_steps is not None:
        plan["steps"] = [_norm_step(s) for s in replace_steps]
    if add_steps:
        for s in add_steps:
            plan["steps"].append(_norm_step(s))
    if complete:
        _complete_steps(plan, complete)
    if notes:
        items = [notes] if isinstance(notes, str) else list(notes)
        for n in items:
            n = str(n).strip()
            if n:
                plan["notes"].append(f"{_now()}: {n}")
    save_plan(project_dir, plan)
    return plan


def _complete_steps(plan: dict[str, Any], complete: list) -> None:
    steps = plan["steps"]
    for c in complete:
        if isinstance(c, int) and 0 <= c < len(steps):
            steps[c]["done"] = True
            continue
        key = str(c).strip().lower()
        for st in steps:
            text = str(st.get("text", ""))
            if text.strip().lower() == key or (key and key in text.lower()):
                st["done"] = True


def render_markdown(plan: dict[str, Any], name: str = "") -> str:
    lines = [f"# {name or 'Project'} workbook", ""]
    if plan.get("goal"):
        lines += ["## Goal", plan["goal"], ""]
    steps = plan.get("steps") or []
    if steps:
        lines.append("## Next steps")
        for st in steps:
            lines.append(f"- [{'x' if st.get('done') else ' '}] {st.get('text','')}")
        lines.append("")
    notes = plan.get("notes") or []
    if notes:
        lines.append("## Notes")
        for n in notes[-_MAX_NOTES:]:
            lines.append(f"- {n}")
        lines.append("")
    if plan.get("updated"):
        lines.append(f"_Updated {plan['updated']}_")
    return "\n".join(lines) + "\n"


def scan_folder(project_dir: str | Path, limit: int = 40) -> dict[str, Any]:
    """Describe a project folder: empty vs existing, top-level entries, plan."""
    base = _base(project_dir)
    exists = base.is_dir()
    entries: list[str] = []
    user_items = 0
    if exists:
        try:
            for p in sorted(base.iterdir()):
                if p.name in _IGNORE:
                    continue
                user_items += 1
                if len(entries) < limit:
                    entries.append(p.name + ("/" if p.is_dir() else ""))
        except OSError:
            pass
    return {
        "path": str(base),
        "exists": exists,
        "empty": exists and user_items == 0,
        "entries": entries,
        "item_count": user_items,
        "has_plan": has_plan(base),
    }


def project_state_block(project_dir: str | Path | None) -> str:
    """A compact context block for the system prompt, or '' if nothing to show."""
    if not project_dir:
        return ""
    base = _base(project_dir)
    plan = load_plan(base)
    if not (plan.get("goal") or plan.get("steps") or plan.get("notes")):
        return ""
    out = ["Project state (keep this in focus across the whole task):",
           f"- Folder: {base}"]
    if plan.get("goal"):
        out.append(f"- Goal: {plan['goal']}")
    steps = plan.get("steps") or []
    if steps:
        out.append("- Plan:")
        for st in steps[:_MAX_STEPS]:
            out.append(f"    [{'x' if st.get('done') else ' '}] {st.get('text','')}")
    notes = plan.get("notes") or []
    if notes:
        out.append("- Recent notes:")
        for n in notes[-5:]:
            out.append(f"    {n}")
    out.append("Keep this current with update_project_plan: mark steps done, add "
               "new ones, and record key decisions, so you never lose the goal.")
    return "\n".join(out)
