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
        "text}]}; decks (pptx) take {slides:[{title, subtitle?, bullets:[...]}]}; "
        "sheets (xlsx/csv) take {rows:[[...],[...]], sheet?}; json takes {data}; "
        "svg/html/txt may take {content}. Give a clear 'name' for the file."
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
