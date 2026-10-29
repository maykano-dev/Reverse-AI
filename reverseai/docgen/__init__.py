"""Dependency-free document & file generation.

One engine that turns a simple spec into a real, downloadable file: PDF, PPTX,
DOCX, XLSX, plus Markdown, HTML, CSV, JSON, SVG, and plain text. Everything is
produced with the standard library, so "generate any file" needs no installs.

    from reverseai.docgen import generate
    f = generate("pdf", {"title": "Report", "blocks": [
        {"type": "heading", "text": "Summary"},
        {"type": "paragraph", "text": "..."},
        {"type": "bullet", "text": "point one"}]})
    f.data      # bytes
    f.filename  # "report.pdf"
    f.mime      # "application/pdf"
"""

from __future__ import annotations

import csv as _csv
import html as _html
import io
import json as _json
from dataclasses import dataclass
from typing import Any

from .docx import DocxDoc, render_docx
from .pdf import PdfDoc, render_pdf
from .pptx import Slide, render_pptx
from .xlsx import render_xlsx

MIME = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "md": "text/markdown",
    "html": "text/html",
    "csv": "text/csv",
    "json": "application/json",
    "svg": "image/svg+xml",
    "txt": "text/plain",
}
KINDS = tuple(MIME)


class DocGenError(Exception):
    pass


@dataclass
class GeneratedFile:
    kind: str
    filename: str
    mime: str
    data: bytes

    def to_meta(self) -> dict[str, Any]:
        return {"kind": self.kind, "filename": self.filename,
                "mime": self.mime, "bytes": len(self.data)}


def _blocks(spec: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for b in spec.get("blocks") or []:
        if isinstance(b, str):
            out.append({"type": "paragraph", "text": b})
        elif isinstance(b, dict):
            out.append({"type": str(b.get("type") or "paragraph"),
                        "text": str(b.get("text") or "")})
    return out


def _slug(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_ " else "" for c in name)
    slug = "-".join(keep.lower().split()) or "document"
    return slug[:60]


def _pdf(spec):
    d = PdfDoc(title=str(spec.get("title") or ""),
               subtitle=str(spec.get("subtitle") or ""))
    for b in _blocks(spec):
        if b["type"] == "subtitle":
            d.subtitle = b["text"]
        else:
            {"heading": d.heading, "bullet": d.bullet}.get(b["type"], d.paragraph)(b["text"])
    return render_pdf(d)


def _docx(spec):
    d = DocxDoc(title=str(spec.get("title") or ""),
                subtitle=str(spec.get("subtitle") or ""))
    for b in spec.get("blocks") or []:
        if isinstance(b, str):
            d.paragraph(b)
            continue
        if not isinstance(b, dict):
            continue
        t = str(b.get("type") or "paragraph")
        if t == "table" and isinstance(b.get("rows"), list):
            d.table(b["rows"])
        elif t == "subtitle":
            d.subtitle = str(b.get("text") or "")
        elif t == "heading":
            d.heading(str(b.get("text") or ""), int(b.get("level") or 1))
        elif t == "bullet":
            d.bullet(str(b.get("text") or ""))
        else:
            d.paragraph(str(b.get("text") or ""))
    return render_docx(d)


def _pptx(spec):
    slides = []
    for s in spec.get("slides") or []:
        if isinstance(s, dict):
            slides.append(Slide(
                title=str(s.get("title") or ""),
                subtitle=str(s.get("subtitle") or ""),
                bullets=[str(x) for x in (s.get("bullets") or [])]))
    if not slides and spec.get("title"):
        slides.append(Slide(title=str(spec["title"])))
    return render_pptx(slides)


def _xlsx(spec):
    rows = spec.get("rows") or []
    return render_xlsx(rows, sheet_name=str(spec.get("sheet") or "Sheet1"))


def _md(spec):
    lines = []
    if spec.get("title"):
        lines.append(f"# {spec['title']}\n")
    for b in _blocks(spec):
        if b["type"] == "heading":
            lines.append(f"## {b['text']}\n")
        elif b["type"] == "bullet":
            lines.append(f"- {b['text']}")
        else:
            lines.append(f"{b['text']}\n")
    body = spec.get("content")
    if body:
        lines.append(str(body))
    return ("\n".join(lines)).encode("utf-8")


def _html_doc(spec):
    if spec.get("content"):
        return str(spec["content"]).encode("utf-8")
    parts = ['<!doctype html><html><head><meta charset="utf-8">',
             f"<title>{_html.escape(str(spec.get('title') or 'Document'))}</title>",
             "<style>body{font:16px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;"
             "max-width:760px;margin:40px auto;padding:0 20px;color:#1d1d1f}"
             "h1{letter-spacing:-.02em}li{margin:.2em 0}</style></head><body>"]
    if spec.get("title"):
        parts.append(f"<h1>{_html.escape(str(spec['title']))}</h1>")
    bullets_open = False
    for b in _blocks(spec):
        if b["type"] == "bullet":
            if not bullets_open:
                parts.append("<ul>")
                bullets_open = True
            parts.append(f"<li>{_html.escape(b['text'])}</li>")
            continue
        if bullets_open:
            parts.append("</ul>")
            bullets_open = False
        if b["type"] == "heading":
            parts.append(f"<h2>{_html.escape(b['text'])}</h2>")
        else:
            parts.append(f"<p>{_html.escape(b['text'])}</p>")
    if bullets_open:
        parts.append("</ul>")
    parts.append("</body></html>")
    return "".join(parts).encode("utf-8")


def _csv_doc(spec):
    out = io.StringIO()
    w = _csv.writer(out)
    for row in spec.get("rows") or []:
        w.writerow(list(row))
    return out.getvalue().encode("utf-8")


def _json_doc(spec):
    data = spec.get("data", spec)
    return _json.dumps(data, indent=2, default=str).encode("utf-8")


def _svg_doc(spec):
    if spec.get("content"):
        return str(spec["content"]).encode("utf-8")
    raise DocGenError("svg requires a 'content' SVG string")


def _txt_doc(spec):
    if spec.get("content"):
        return str(spec["content"]).encode("utf-8")
    return _md(spec)


_BUILDERS = {
    "pdf": _pdf, "pptx": _pptx, "docx": _docx, "xlsx": _xlsx,
    "md": _md, "html": _html_doc, "csv": _csv_doc, "json": _json_doc,
    "svg": _svg_doc, "txt": _txt_doc,
}


def generate(kind: str, spec: dict[str, Any] | None = None, *,
             name: str | None = None) -> GeneratedFile:
    kind = (kind or "").lower().lstrip(".")
    if kind in ("ppt", "powerpoint"):
        kind = "pptx"
    if kind in ("doc", "word"):
        kind = "docx"
    if kind in ("xls", "excel", "spreadsheet"):
        kind = "xlsx"
    if kind in ("markdown",):
        kind = "md"
    if kind not in _BUILDERS:
        raise DocGenError(f"unsupported kind {kind!r}; use one of {', '.join(KINDS)}")
    spec = spec or {}
    if not isinstance(spec, dict):
        raise DocGenError("spec must be an object")
    data = _BUILDERS[kind](spec)
    base = _slug(name or spec.get("title") or spec.get("name") or kind)
    if not base.endswith("." + kind):
        base = f"{base}.{kind}"
    return GeneratedFile(kind=kind, filename=base, mime=MIME[kind], data=data)
