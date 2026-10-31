"""Project tools: point the agent at a folder and keep a durable plan.

- ``set_project_folder`` binds the conversation to a real folder on disk. The
  coding tools then read and write there. If the folder is empty the agent helps
  start a project; if it already has code, the agent continues it.
- ``update_project_plan`` / ``read_project_plan`` maintain a small workbook in
  that folder (goal + next-steps + notes). The workbook is injected into context
  every turn, so a long build keeps its focus on the goal.
"""

from __future__ import annotations

from pathlib import Path

from .tools import Permission, Tool, ToolResult


def _proj(ctx) -> str:
    return ctx.extra.get("project_dir") or ctx.workspace


class SetProjectFolderTool(Tool):
    name = "set_project_folder"
    description = (
        "Point yourself at a folder on the user's machine to work in - the "
        "project directory your file, search, and git tools then operate on. "
        "Give 'path' (absolute, or relative to where the app runs). Use "
        "create=true to make it if it does not exist. It reports whether the "
        "folder is EMPTY (help the user start/scaffold a project) or already has "
        "code (continue it), plus a top-level listing and whether a saved plan "
        "exists. Call this when the user names a folder or asks to work on a "
        "local project, then keep a plan with update_project_plan."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "folder to work in"},
            "create": {"type": "boolean", "default": False,
                       "description": "create the folder if missing"},
        },
        "required": ["path"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        from ..project import load_plan, scan_folder

        raw = str(args.get("path") or "").strip()
        if not raw:
            return ToolResult.failure("a folder path is required")
        try:
            base = Path(raw).expanduser()
            if not base.is_absolute():
                base = Path.cwd() / base
            base = base.resolve()
        except (OSError, RuntimeError) as exc:
            return ToolResult.failure(f"invalid path: {exc}")
        if not base.exists():
            if not args.get("create"):
                return ToolResult.failure(
                    f"no such folder: {base} (pass create=true to make it)")
            try:
                base.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                return ToolResult.failure(f"could not create folder: {exc}")
        if not base.is_dir():
            return ToolResult.failure(f"not a folder: {base}")

        ctx.extra["project_dir"] = str(base)
        info = scan_folder(base)
        lines = [f"working folder set to {base}"]
        if info["empty"]:
            lines.append("the folder is empty - help the user start a new project here.")
        else:
            listing = ", ".join(info["entries"][:20]) or "(contents hidden)"
            lines.append(f"existing project ({info['item_count']} items): {listing}")
        if info["has_plan"]:
            plan = load_plan(base)
            open_steps = [s["text"] for s in plan.get("steps", []) if not s.get("done")]
            if plan.get("goal"):
                lines.append(f"saved goal: {plan['goal']}")
            if open_steps:
                lines.append("open steps: " + "; ".join(open_steps[:6]))
        else:
            lines.append("no saved plan yet - set one with update_project_plan.")
        return ToolResult.success("\n".join(lines), **info)


class UpdateProjectPlanTool(Tool):
    name = "update_project_plan"
    description = (
        "Maintain the project's workbook (goal + a next-steps checklist + notes) "
        "so you keep focus across a long task. Set 'goal' once; add new TODOs "
        "with 'add_steps'; mark progress with 'complete' (step text or index); "
        "record a key decision or fact with 'note'. Use 'replace_steps' to reset "
        "the whole list. The workbook is saved in the project folder and is shown "
        "back to you every turn. Update it as you work, not just at the end."
    )
    parameters = {
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "add_steps": {"type": "array", "items": {"type": "string"}},
            "complete": {"type": "array", "items": {"type": "string"},
                         "description": "step texts (or indices) now done"},
            "replace_steps": {"type": "array", "items": {"type": "string"}},
            "note": {"type": "string", "description": "a decision or fact to record"},
        },
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        from ..project import render_markdown, update_plan

        complete = args.get("complete") or []
        norm = []
        for c in complete:
            try:
                norm.append(int(c))
            except (TypeError, ValueError):
                norm.append(c)
        plan = update_plan(
            _proj(ctx),
            goal=args.get("goal"),
            add_steps=args.get("add_steps"),
            complete=norm,
            replace_steps=args.get("replace_steps"),
            notes=args.get("note"),
        )
        done = sum(1 for s in plan.get("steps", []) if s.get("done"))
        total = len(plan.get("steps", []))
        return ToolResult.success(
            render_markdown(plan), goal=plan.get("goal", ""),
            steps_done=done, steps_total=total)


class ReadProjectPlanTool(Tool):
    name = "read_project_plan"
    description = (
        "Read the project's current workbook (goal, next steps, notes). It is "
        "also injected into your context each turn, so use this when you want "
        "the full, up-to-date plan on demand."
    )
    parameters = {"type": "object", "properties": {}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from ..project import has_plan, render_markdown, load_plan

        proj = _proj(ctx)
        if not has_plan(proj):
            return ToolResult.success(
                "no project plan yet. Set a goal and steps with update_project_plan.",
                exists=False)
        return ToolResult.success(render_markdown(load_plan(proj)), exists=True)


def project_tools() -> list[Tool]:
    return [SetProjectFolderTool(), UpdateProjectPlanTool(), ReadProjectPlanTool()]
