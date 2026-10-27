"""Agent tool for creating interactive surfaces in the conversation."""

from __future__ import annotations

from typing import Any

from ..surface import SurfaceError, validate_surface
from .tools import Permission, Tool, ToolContext, ToolResult


class CreateSurfaceTool(Tool):
    name = "create_surface"
    description = (
        "Create an interactive surface inside the chat: a clarification question, "
        "form, table, chart, graph, diff, code view, progress panel, approval card, "
        "file drop zone, dashboard, or sandboxed custom view. Use it when the user "
        "needs to see, choose, edit, approve, or explore something directly. Every "
        "choice block gets an 'Other — type your own' escape hatch by default. The "
        "surface is data; actions still go through the normal permission gates."
    )
    parameters = {
        "type": "object",
        "properties": {
            "surface": {
                "type": "object",
                "description": "the complete surface spec; if omitted, build one "
                               "from kind/title/blocks/actions",
            },
            "kind": {
                "type": "string",
                "enum": ["question", "form", "dashboard", "review", "approval",
                         "progress", "custom", "workspace"],
            },
            "title": {"type": "string"},
            "description": {"type": "string"},
            "blocks": {"type": "array", "items": {"type": "object"}},
            "actions": {"type": "array", "items": {"type": "object"}},
            "allow_other": {"type": "boolean", "default": True},
            "persist": {"type": "boolean", "default": True},
            "wait": {
                "type": "boolean",
                "description": "pause this turn and wait for the user's response; "
                               "defaults to true for question/form/approval",
            },
        },
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        spec = args.get("surface")
        if not isinstance(spec, dict):
            spec = {
                "kind": args.get("kind") or "question",
                "title": args.get("title") or "Decision",
                "description": args.get("description") or "",
                "blocks": args.get("blocks") or [],
                "actions": args.get("actions") or [],
                "allow_other": args.get("allow_other", True),
                "persist": args.get("persist", True),
                "wait": args.get("wait", True),
            }
        else:
            spec = dict(spec)
            for key in ("kind", "title", "description", "blocks", "actions",
                        "allow_other", "persist", "wait"):
                if key in args and key not in spec:
                    spec[key] = args[key]
        spec.setdefault("meta", {})
        if ctx.job_id:
            spec["meta"]["created_by_job"] = ctx.job_id
        try:
            surface = validate_surface(spec)
        except SurfaceError as exc:
            return ToolResult.failure(f"invalid surface: {exc}")
        surfaces = list(ctx.extra.get("surfaces") or [])
        surfaces = [s for s in surfaces if s.get("id") != surface["id"]]
        surfaces.append(surface)
        ctx.extra["surfaces"] = surfaces
        if surface.get("wait"):
            ctx.extra["pending_surface"] = surface
        emit = ctx.extra.get("emit")
        if callable(emit):
            try:
                emit({"type": "surface", "job_id": ctx.job_id,
                      "surface": surface})
            except Exception:
                pass
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"created interactive surface: {surface['title']}",
                source=self.name)
        return ToolResult.success(
            f"created surface {surface['id']}: {surface['title']} "
            f"({len(surface['blocks'])} block(s))",
            surface=surface, surfaces=surfaces)


def surface_tools() -> list[Tool]:
    return [CreateSurfaceTool()]
