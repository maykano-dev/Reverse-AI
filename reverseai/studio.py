"""In-app document & deck Studio: edit a generated file and regenerate it.

The source of truth for an editable deliverable is its *spec* (the same simple
JSON the agent passed to `create_document`). When a file is generated we keep a
sidecar spec under ``<workspace>/.studio/<filename>.json``. The Studio UI loads
that spec, lets the user edit it, and posts it back; we regenerate the real file
(PPTX/DOCX/PDF/...) from the edited spec with the dependency-free docgen engine.

This keeps editing honest: we never reverse-engineer a binary Office file in the
browser. We edit structured content and re-render it with the same renderer that
produced it, so the downloaded file is always a real, valid document.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .docgen import KINDS, DocGenError, generate

_DIRNAME = ".studio"
# Kinds that have a structured editor in the UI. Others keep a sidecar so they
# can still be regenerated, but open as plain content.
EDITABLE = ("pptx", "docx", "pdf", "md", "html", "xlsx", "txt")


class StudioError(Exception):
    pass


def _safe_name(filename: str) -> str:
    raw = str(filename or "")
    name = Path(raw).name
    # Reject anything that is not already a bare, safe basename rather than
    # silently collapsing "../x" to "x".
    if (not name or name in (".", "..") or name != raw
            or "/" in raw or "\\" in raw):
        raise StudioError("invalid filename")
    return name


def studio_dir(workspace: str | Path) -> Path:
    d = Path(workspace) / _DIRNAME
    return d


def _sidecar(workspace: str | Path, filename: str) -> Path:
    return studio_dir(workspace) / (_safe_name(filename) + ".json")


def _json_safe(value):
    """Recursively drop bytes values so a spec can be stored as JSON."""
    if isinstance(value, (bytes, bytearray)):
        return None
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            sv = _json_safe(v)
            if sv is not None or not isinstance(v, (bytes, bytearray)):
                out[k] = sv
        return out
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _strip_bytes(spec: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe copy of a spec: drop embedded image bytes, keep src."""
    return _json_safe(spec)


def _read_image(workspace, src):
    from .docgen.images import ImageError, decode_image
    if not isinstance(src, str) or not src:
        return None
    try:
        p = _safe_join_ws(workspace, src)
        if p.is_file() and p.stat().st_size <= 12 * 1024 * 1024:
            data = p.read_bytes()
            img = decode_image(data)       # validate + get dimensions
            return data, img.width, img.height
    except (OSError, ValueError, ImageError):
        return None
    return None


def _raster_svg(svg):
    """Rasterize an SVG string to (png_bytes, w, h), or None."""
    from .docgen.images import ImageError, decode_image
    from .docgen.svgraster import svg_to_png
    if not isinstance(svg, str) or "<svg" not in svg.lower():
        return None
    png = svg_to_png(svg)
    if not png:
        return None
    try:
        img = decode_image(png)
        return png, img.width, img.height
    except ImageError:
        return None


def _chart_colors(spec):
    try:
        from .docgen.pptx import resolve_theme
        t = resolve_theme(spec.get("theme"))
        return {"bg": t["bg"], "ink": t["ink"], "muted": t["muted"],
                "accent": t["accent"], "accent2": t["accent2"],
                "font": t["fonts"]["body"]}
    except Exception:
        return {}


def embed_images(spec: dict[str, Any], workspace: str | Path) -> None:
    """Resolve image src references, charts, and inline SVG to embedded bytes.

    Keeps the pure renderer off the filesystem: paths are read and validated
    here, charts are drawn as SVG, and the model's SVG art is rasterized.
    """
    from .docgen.charts import render_chart
    # If a deck has no theme, pick a varied one now (deterministic by title) so
    # the whole deck - slides AND charts/art colors - shares one look, instead
    # of charts defaulting to the light-blue palette while the deck renders dark.
    if not spec.get("theme") and spec.get("slides"):
        try:
            from .docgen.pptx import auto_theme
            title = next((s.get("title") for s in spec["slides"]
                          if isinstance(s, dict) and s.get("title")), "deck")
            spec["theme"] = auto_theme(title)
        except Exception:  # pragma: no cover - best-effort
            pass
    colors = _chart_colors(spec)
    # Turn chart specs into SVG first; the SVG path below rasterizes them.
    for s in spec.get("slides") or []:
        if isinstance(s, dict) and s.get("chart") and not s.get("svg") and not s.get("image_data"):
            svg = render_chart({**s["chart"], "background": True}, colors)
            if svg:
                s["svg"] = svg
    for b in spec.get("blocks") or []:
        if isinstance(b, dict) and b.get("chart") and not b.get("svg") and not b.get("data"):
            svg = render_chart({**b["chart"], "background": True}, colors)
            if svg:
                b["svg"] = svg
    for b in spec.get("blocks") or []:
        if not isinstance(b, dict) or b.get("data"):
            continue
        if b.get("svg"):
            got = _raster_svg(b.get("svg"))
            if got:
                b["type"] = "image"
                b["data"], b["img_w"], b["img_h"] = got
        elif b.get("type") == "image":
            got = _read_image(workspace, b.get("src") or b.get("path"))
            if got:
                b["data"], b["img_w"], b["img_h"] = got
    for s in spec.get("slides") or []:
        if not isinstance(s, dict) or s.get("image_data"):
            continue
        if s.get("svg"):
            got = _raster_svg(s.get("svg"))
            if got:
                s["image_data"], s["image_w"], s["image_h"] = got
        elif s.get("image"):
            got = _read_image(workspace, s.get("image"))
            if got:
                s["image_data"], s["image_w"], s["image_h"] = got


def _safe_join_ws(workspace: str | Path, rel: str) -> Path:
    from .security.validate import safe_join
    return safe_join(Path(workspace), rel)


def save_spec(workspace: str | Path, filename: str, kind: str,
              spec: dict[str, Any], name: str | None = None) -> None:
    """Persist the spec that produced ``filename`` so it can be edited later."""
    d = studio_dir(workspace)
    try:
        d.mkdir(parents=True, exist_ok=True)
        record = {"kind": kind, "name": name or filename, "spec": _strip_bytes(spec)}
        _sidecar(workspace, filename).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        # A missing sidecar only means "not editable in Studio"; never fail the
        # original generation because the sidecar could not be written.
        pass


def load_spec(workspace: str | Path, filename: str) -> dict[str, Any]:
    name = _safe_name(filename)
    side = _sidecar(workspace, name)
    if not side.is_file():
        raise StudioError("this file was not generated here, so it cannot be edited")
    try:
        record = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StudioError(f"could not read Studio data: {exc}") from exc
    if not isinstance(record, dict) or "spec" not in record:
        raise StudioError("Studio data is malformed")
    record.setdefault("kind", name.rsplit(".", 1)[-1].lower())
    record.setdefault("name", name)
    record["filename"] = name
    return record


@dataclass
class Rendered:
    filename: str
    kind: str
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def _base(filename: str) -> str:
    name = _safe_name(filename)
    return name.rsplit(".", 1)[0] if "." in name else name


def regenerate(workspace: str | Path, filename: str,
               spec: dict[str, Any]) -> Rendered:
    """Re-render ``filename`` from an edited spec and overwrite it on disk."""
    record = load_spec(workspace, filename)
    kind = record["kind"]
    if not isinstance(spec, dict):
        raise StudioError("spec must be an object")
    embed_images(spec, workspace)
    try:
        out = generate(kind, spec, name=_base(filename))
    except DocGenError as exc:
        raise StudioError(str(exc)) from exc
    name = _safe_name(filename)
    target = Path(workspace) / name
    try:
        target.write_bytes(out.data)
    except OSError as exc:
        raise StudioError(f"could not write file: {exc}") from exc
    save_spec(workspace, name, kind, spec, record.get("name"))
    return Rendered(filename=name, kind=kind, data=out.data)


def _deck_to_pdf_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Flatten a deck into a readable document for PDF export."""
    blocks: list[dict[str, Any]] = []
    slides = spec.get("slides") or []
    title = ""
    for i, s in enumerate(slides):
        if not isinstance(s, dict):
            continue
        head = str(s.get("title") or s.get("quote") or f"Slide {i + 1}")
        if i == 0 and not title:
            title = head
        blocks.append({"type": "heading", "text": head})
        if s.get("subtitle"):
            blocks.append({"type": "paragraph", "text": str(s["subtitle"])})
        if s.get("quote"):
            blocks.append({"type": "paragraph", "text": str(s["quote"])})
        if s.get("attribution"):
            blocks.append({"type": "paragraph", "text": "- " + str(s["attribution"])})
        for b in s.get("bullets") or []:
            blocks.append({"type": "bullet", "text": str(b)})
        for col in s.get("columns") or []:
            for b in col or []:
                blocks.append({"type": "bullet", "text": str(b)})
    return {"title": title or str(spec.get("title") or "Presentation"),
            "blocks": blocks}


def export(workspace: str | Path, filename: str, fmt: str) -> Rendered:
    """Render the current spec to another format (e.g. a deck to PDF)."""
    record = load_spec(workspace, filename)
    kind = record["kind"]
    spec = record["spec"]
    fmt = (fmt or "").lower().lstrip(".")
    if fmt in ("ppt", "powerpoint"):
        fmt = "pptx"
    if fmt in ("doc", "word"):
        fmt = "docx"
    if fmt not in KINDS:
        raise StudioError(f"cannot export to {fmt!r}")
    base = _base(filename)
    if fmt == "pdf" and kind == "pptx":
        spec = _deck_to_pdf_spec(spec)
    embed_images(spec, workspace)
    try:
        out = generate(fmt, spec, name=base)
    except DocGenError as exc:
        raise StudioError(str(exc)) from exc
    return Rendered(filename=out.filename, kind=fmt, data=out.data)
