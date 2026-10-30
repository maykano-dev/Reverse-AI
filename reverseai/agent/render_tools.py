"""Agent tool: render a generated document to page images and (optionally) see it.

This is the visual self-check. After producing a deck, PDF, or document, the
agent can render it to images, look at it (when a vision backend is configured),
and fix layout before delivering. The rendered pages are also surfaced to the
user so they can view the output in the chat.
"""

from __future__ import annotations

from pathlib import Path

from ..security.validate import safe_join
from .tools import Permission, Tool, ToolResult

_CRITIQUE_PROMPT = (
    "You are reviewing a rendered page of a generated document or slide. "
    "Describe briefly what is on it, then flag any layout problems: text cut off "
    "or overflowing, elements overlapping, large empty gaps, poor contrast or "
    "unreadable text, misalignment, or a title/body that collides. If it looks "
    "clean, say so. Be specific and concise."
)


class RenderDocumentTool(Tool):
    name = "render_document"
    description = (
        "Render a generated file (pdf, pptx, docx, xlsx) to page images so you "
        "can SEE how it actually looks and fix layout before delivering. Call it "
        "after create_document on anything visual. It returns the page images "
        "(also shown to the user); if a vision backend is configured it also "
        "returns a visual check of each page so you can spot overflow, overlap, "
        "empty space, or bad contrast and regenerate if needed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "workspace file to render (defaults to the "
                                    "last file you generated)"},
            "max_pages": {"type": "integer",
                          "description": "maximum pages to render (default 8)"},
        },
    }
    permission = Permission.EXECUTE

    def run(self, args, ctx) -> ToolResult:
        from ..docgen.render import RenderError, render_file

        rel = str(args.get("path") or ctx.extra.get("modified_path") or "").strip()
        if not rel:
            return ToolResult.failure("no file to render; generate one first or pass 'path'")
        ws = Path(ctx.workspace).resolve()
        try:
            cand = Path(rel)
            if cand.is_absolute():
                target = cand.resolve()
                target.relative_to(ws)       # must be inside the workspace
            else:
                target = safe_join(ws, rel)
        except (ValueError, OSError):
            return ToolResult.failure("the file must be inside this workspace")

        out = ws / ".render"
        try:
            pages = render_file(target, out, max_pages=int(args.get("max_pages") or 8))
        except RenderError as exc:
            return ToolResult.failure(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult.failure(f"rendering failed: {exc}")

        conv = ws.name
        rels = [".render/" + Path(p).name for p in pages]
        urls = [f"/preview/{conv}/{r}" for r in rels]
        # Surface the renders to the UI (shown as thumbnails under the answer).
        seen = ctx.extra.setdefault("renders", [])
        for u in urls:
            if u not in seen:
                seen.append(u)

        from .. import vision
        critique = ""
        has_vision = vision.available()
        if has_vision:
            parts = []
            for i, p in enumerate(pages[:6], start=1):
                try:
                    data = Path(p).read_bytes()
                    res = vision.describe_image(data, "image/png", prompt=(
                        f"Page {i} of {target.name}. " + _CRITIQUE_PROMPT))
                    parts.append(f"Page {i}: {res.get('text') or res.get('description') or res}")
                except vision.VisionError as exc:
                    parts.append(f"Page {i}: (could not inspect: {exc})")
            critique = "\n".join(parts)

        msg = f"rendered {len(pages)} page(s) of {target.name}"
        if critique:
            msg += "\n\nVisual check:\n" + critique
        elif not has_vision:
            msg += (". No vision backend is configured, so I can't inspect them "
                    "automatically; the pages are shown to the user to review.")
        if ctx.evidence is not None:
            ctx.evidence.observed(f"rendered {len(pages)} page(s) of {target.name}",
                                  source=self.name)
        return ToolResult.success(msg, pages=rels, urls=urls,
                                  vision=has_vision, critique=critique)
