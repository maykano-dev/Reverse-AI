"""Agent tool: generate a real file to hand back (PDF, PPTX, DOCX, XLSX, ...).

This is the "generate any file" capability. It writes the file into the job
workspace and marks it as a fresh deliverable (no binary verification needed,
like a cloned site bundle), so the UI offers it for download.
"""

from __future__ import annotations

from pathlib import Path

from ..docgen import KINDS, DocGenError, generate
from ..security.validate import safe_join
from .tools import Permission, Tool, ToolContext, ToolResult


def _invalidate(ctx: ToolContext) -> None:
    for key in ("verification", "delivery", "differential"):
        ctx.extra.pop(key, None)


class CreateDocumentTool(Tool):
    name = "create_document"
    description = (
        "Generate a real, downloadable file and deliver it: a PDF, a PowerPoint "
        "deck (pptx), a Word document (docx), an Excel sheet (xlsx), or markdown/"
        "html/csv/json/svg/txt. Use this when the user wants a document, report, "
        "deck, or spreadsheet. The 'spec' shape depends on kind: documents (pdf/"
        "docx/md/html) take {title, blocks:[{type:'heading'|'paragraph'|'bullet', "
        "text}]}; decks (pptx) take {theme, slides:[...]}. Decks are DESIGNED: set "
        "'theme' to a preset (light, slate, midnight, aurora, sunset, forest, mono) "
        "or an object {preset?, bg, surface, ink, muted, accent, accent2, "
        "fonts:{title,body}} - use real colors and dark backgrounds, not white, "
        "unless white is wanted. Each slide may set 'layout': cover (title + "
        "subtitle), section (full-accent divider), content ({title, subtitle?, "
        "bullets}), two-column ({title, columns:[[...],[...]]}), quote ({quote, "
        "attribution}), statement ({title}), or 'cards' (a tidy grid - "
        "'cards':[{num? or label?, title, text?}] - for a roadmap/agenda of "
        "numbered items or labeled callouts); plus per-slide 'bg'/'accent' "
        "overrides. Pick a theme that fits the topic and vary the layouts. A good "
        "deck is NOT a wall of bullet lists: open with a 'cover', put a 'section' "
        "divider between parts, turn any process, pipeline, or comparison into a "
        "'diagram' slide, use 'two-column' or an 'image' where it helps, and end "
        "on a 'quote' or 'statement'. Aim for 3-5 short bullets per slide and at "
        "least one visual (diagram or image) in any deck of 3+ slides. A slide "
        "can include an image ('image':'assets/x.png'; layout 'image' for a big "
        "figure, or with bullets for text+image) or a DIAGRAM. For a process, "
        "pipeline, or sequence, use layout 'diagram' with 'steps':['A','B','C'] "
        "(3-5 short labels) - the engine lays out tidy, equal, evenly-spaced "
        "boxes with arrows and centered text automatically; prefer this. For "
        "parallel items use 'diagram_style':'pillars'. Only use raw 'shapes' "
        "coordinates for a custom drawing. A subtle entrance fade is 'animate':"
        "true on the deck or a slide. For a polished look add a 'kicker' (short "
        "eyebrow label above the title) and a deck 'footer' (auto page numbers "
        "are added). Backgrounds: set 'bg_style' (mesh|geometric|glow|rings|"
        "diagonal|plain), or COMPOSE your own with 'bg_spec':{fill:{type:'gradient'"
        ",from,to,angle} or {type:'solid',color}, shapes:[{type:'ellipse'|'rect'|"
        "'ring'|'line', x,y,w,h as 0-100 percent, color, alpha 0-100, rot, x2,y2}]} "
        "- design freely, keep shapes low-alpha behind the text. Restrained "
        "backgrounds with strong content usually look best. For BESPOKE art (a "
        "chart, waveform, circuit, timeline, illustration) draw it in SVG and set "
        "'svg':'<svg viewBox=\"0 0 1000 620\">...</svg>' on a slide (or a block "
        "{type:'image', svg:'...'} in a pdf/doc); it is rasterized and embedded. "
        "Give the svg a background rect in the slide's colors for full-bleed, or "
        "leave it transparent for a figure card. "
        "sheets (xlsx/csv) take {rows:[[...],[...]], sheet?}; "
        "json takes {data}; svg/html/txt may take {content}. To place a picture in "
        "a pdf or Word doc, add a block {type:'image', src:'assets/photo.png', "
        "caption?, width?} where 'src' is a PNG/JPEG already in the workspace (e.g. "
        "from install_media). A pdf can also contain a drawn diagram block "
        "{type:'diagram', height?, shapes:[{type:'rect'|'roundrect'|'ellipse'|"
        "'line'|'arrow'|'text', x,y,w,h as 0-100 percent, x2/y2 for lines, color, "
        "text, text_color}]} to draw flows and boxes inline. Give a clear 'name' "
        "for the file. To CHANGE a file "
        "you already generated, call this again with the same 'name' and the full "
        "updated spec: it regenerates and re-delivers the file with a download "
        "link. Never hand-edit the packaged file with shell or write_file - always "
        "regenerate through this tool so the user gets a clickable, downloadable "
        "result. After making a visual file (deck/pdf/docx), call render_document "
        "to see how it actually looks and fix any layout problems before finishing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(KINDS),
                     "description": "file type to generate"},
            "spec": {"type": "object",
                     "description": "content spec (shape depends on kind)"},
            "name": {"type": "string",
                     "description": "descriptive file name (no extension needed)"},
        },
        "required": ["kind", "spec"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        kind = str(args.get("kind") or "").strip()
        spec = args.get("spec")
        if not isinstance(spec, dict):
            return ToolResult.failure("'spec' must be an object")
        try:
            from ..studio import embed_images
            embed_images(spec, ctx.workspace)
        except Exception:  # pragma: no cover - image resolution is best-effort
            pass
        try:
            doc = generate(kind, spec, name=args.get("name"))
        except DocGenError as exc:
            return ToolResult.failure(str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            return ToolResult.failure(f"generation failed: {exc}")

        try:
            out = safe_join(Path(ctx.workspace), doc.filename)
            out.write_bytes(doc.data)
        except OSError as exc:
            return ToolResult.failure(f"could not write file: {exc}")

        # Keep the spec so the file can be reopened and edited in the Studio.
        try:
            from ..studio import save_spec
            save_spec(ctx.workspace, doc.filename, doc.kind, spec,
                      name=args.get("name"))
        except Exception:  # pragma: no cover - sidecar is best-effort
            pass

        _invalidate(ctx)
        ctx.extra["modified_path"] = str(out)
        ctx.extra["modified_operation"] = "document"
        ctx.extra["modified_turn"] = ctx.job_id
        ctx.extra["modified_label"] = f"Generated {doc.kind.upper()}"
        if ctx.evidence is not None:
            ctx.evidence.verified(
                f"generated {doc.filename} ({len(doc.data)} bytes)",
                source=self.name)
        return ToolResult.success(
            f"generated {doc.filename} ({len(doc.data)} bytes, {doc.mime})",
            **doc.to_meta(), path=str(out))
