"""A starter set of deterministic, model-free capability evals.

Each case exercises a real capability end to end and asserts on the outcome.
They need no API key, so they can run on every change.
"""

from __future__ import annotations

import struct
import tempfile
import zipfile
import zlib
from io import BytesIO
from pathlib import Path

from .harness import Case


def _png(w, h):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        for x in range(w):
            raw += bytes([(x * 255) // max(1, w - 1), 120, (y * 255) // max(1, h - 1)])

    def ch(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n"
            + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + ch(b"IDAT", zlib.compress(bytes(raw)))
            + ch(b"IEND", b""))


# --- docgen ----------------------------------------------------------------
def _pdf_valid():
    from reverseai.docgen import generate
    d = generate("pdf", {"title": "T", "blocks": [
        {"type": "heading", "text": "H"}, {"type": "bullet", "text": "point"}]}).data
    assert d.startswith(b"%PDF-"), "not a PDF"
    assert b"startxref" in d and b"%%EOF" in d, "missing trailer"


def _pptx_valid():
    from reverseai.docgen import generate
    d = generate("pptx", {"slides": [{"title": "A", "bullets": ["x"]}]}).data
    z = zipfile.ZipFile(BytesIO(d))
    assert z.testzip() is None, "corrupt zip"
    assert "ppt/presentation.xml" in z.namelist()


def _pptx_theme_dark():
    from reverseai.docgen import generate
    from reverseai.docgen.pptx import PRESETS
    d = generate("pptx", {"theme": "midnight", "slides": [
        {"layout": "cover", "title": "x", "subtitle": "y"}]}).data
    s = zipfile.ZipFile(BytesIO(d)).read("ppt/slides/slide1.xml").decode()
    assert PRESETS["midnight"]["bg"] in s, "dark background not applied"


def _pptx_all_layouts():
    from reverseai.docgen import generate
    spec = {"slides": [
        {"layout": "cover", "title": "c", "subtitle": "s"},
        {"layout": "section", "title": "sec"},
        {"layout": "content", "title": "c", "bullets": ["a", "b"]},
        {"layout": "two-column", "title": "t", "columns": [["x"], ["y"]]},
        {"layout": "quote", "quote": "q", "attribution": "me"},
        {"layout": "statement", "title": "big"}]}
    z = zipfile.ZipFile(BytesIO(generate("pptx", spec).data))
    assert z.testzip() is None
    n = len([x for x in z.namelist() if x.startswith("ppt/slides/slide") and x.endswith(".xml")])
    assert n == 6, f"expected 6 slides, got {n}"


def _pptx_image_embed():
    from reverseai.docgen import generate
    from reverseai.studio import embed_images
    ws = tempfile.mkdtemp()
    (Path(ws) / "assets").mkdir()
    (Path(ws) / "assets" / "p.png").write_bytes(_png(40, 30))
    spec = {"slides": [{"layout": "image", "title": "p", "image": "assets/p.png"}]}
    embed_images(spec, ws)
    z = zipfile.ZipFile(BytesIO(generate("pptx", spec).data))
    assert any("media/image" in n for n in z.namelist()), "no media part"
    assert b"<p:pic>" in z.read("ppt/slides/slide1.xml")


def _pptx_diagram():
    from reverseai.docgen import generate
    spec = {"slides": [{"layout": "diagram", "title": "f", "shapes": [
        {"type": "roundrect", "x": 5, "y": 30, "w": 20, "h": 18, "text": "A"},
        {"type": "arrow", "x": 25, "y": 39, "x2": 45, "y2": 39}]}]}
    s = zipfile.ZipFile(BytesIO(generate("pptx", spec).data)).read("ppt/slides/slide1.xml")
    assert b'prst="line"' in s and b"tailEnd" in s, "arrow not drawn"


def _pptx_flow_autolayout():
    from reverseai.docgen import generate
    spec = {"slides": [{"layout": "diagram", "title": "f",
                        "steps": ["One", "Two", "Three"]}]}
    s = zipfile.ZipFile(BytesIO(generate("pptx", spec).data)).read("ppt/slides/slide1.xml")
    assert b"roundRect" in s and b"tailEnd" in s, "flow not laid out"
    assert s.count(b"roundRect") == 3, "expected 3 equal boxes"


def _pdf_image_embed():
    from reverseai.docgen import generate
    from reverseai.studio import embed_images
    ws = tempfile.mkdtemp()
    (Path(ws) / "assets").mkdir()
    (Path(ws) / "assets" / "g.png").write_bytes(_png(32, 24))
    spec = {"title": "i", "blocks": [{"type": "image", "src": "assets/g.png"}]}
    embed_images(spec, ws)
    d = generate("pdf", spec).data
    assert b"/Subtype /Image" in d and b"/DeviceRGB" in d, "image not embedded"


def _pdf_diagram():
    from reverseai.docgen import generate
    spec = {"title": "f", "blocks": [{"type": "diagram", "shapes": [
        {"type": "rect", "x": 5, "y": 30, "w": 20, "h": 18, "text": "A"},
        {"type": "arrow", "x": 25, "y": 39, "x2": 45, "y2": 39}]}]}
    d = generate("pdf", spec).data
    assert b" re f" in d and b" l S" in d, "shapes not drawn"


def _docx_valid():
    from reverseai.docgen import generate
    d = generate("docx", {"title": "T", "blocks": [{"type": "paragraph", "text": "p"}]}).data
    z = zipfile.ZipFile(BytesIO(d))
    assert z.testzip() is None and "word/document.xml" in z.namelist()


def _docx_image():
    from reverseai.docgen import generate
    from reverseai.studio import embed_images
    ws = tempfile.mkdtemp()
    (Path(ws) / "assets").mkdir()
    (Path(ws) / "assets" / "p.png").write_bytes(_png(30, 20))
    spec = {"title": "d", "blocks": [{"type": "image", "src": "assets/p.png"}]}
    embed_images(spec, ws)
    z = zipfile.ZipFile(BytesIO(generate("docx", spec).data))
    assert any("word/media/image" in n for n in z.namelist())
    assert b"<w:drawing>" in z.read("word/document.xml")


def _xlsx_valid():
    from reverseai.docgen import generate
    d = generate("xlsx", {"rows": [["A", "B"], [1, 2]]}).data
    z = zipfile.ZipFile(BytesIO(d))
    assert z.testzip() is None


# --- images ----------------------------------------------------------------
def _png_decode():
    from reverseai.docgen.images import decode_image
    img = decode_image(_png(12, 8))
    assert (img.width, img.height) == (12, 8)
    assert len(img.data) == 12 * 8 * 3


# --- render ----------------------------------------------------------------
def _render_pdf():
    from reverseai.docgen import generate
    from reverseai.docgen.render import render_file
    ws = tempfile.mkdtemp()
    f = Path(ws) / "d.pdf"
    f.write_bytes(generate("pdf", {"title": "T", "blocks": [
        {"type": "paragraph", "text": "hi"}]}).data)
    pages = render_file(f, Path(ws) / "r", dpi=72, max_pages=2)
    assert pages and Path(pages[0]).stat().st_size > 200


def _render_pptx():
    from reverseai.docgen import generate
    from reverseai.docgen.render import render_file
    ws = tempfile.mkdtemp()
    f = Path(ws) / "d.pptx"
    f.write_bytes(generate("pptx", {"slides": [{"title": "A"}, {"title": "B"}]}).data)
    pages = render_file(f, Path(ws) / "r", dpi=72, max_pages=4)
    assert len(pages) >= 1


# --- studio ----------------------------------------------------------------
def _studio_roundtrip():
    from reverseai import studio
    ws = tempfile.mkdtemp()
    spec = {"slides": [{"title": "One", "bullets": ["a"]}]}
    studio.save_spec(ws, "deck.pptx", "pptx", spec, name="deck")
    rec = studio.load_spec(ws, "deck.pptx")
    assert rec["kind"] == "pptx"
    out = studio.regenerate(ws, "deck.pptx", {"slides": [{"title": "Two"}]})
    assert out.data.startswith(b"PK")
    assert studio.load_spec(ws, "deck.pptx")["spec"]["slides"][0]["title"] == "Two"


def _studio_export_pdf():
    from reverseai import studio
    ws = tempfile.mkdtemp()
    studio.save_spec(ws, "deck.pptx", "pptx",
                     {"slides": [{"title": "X", "bullets": ["y"]}]}, name="deck")
    out = studio.export(ws, "deck.pptx", "pdf")
    assert out.kind == "pdf" and out.data.startswith(b"%PDF-")


CASES = [
    Case("pdf_valid", "docgen", _pdf_valid),
    Case("pptx_valid", "docgen", _pptx_valid),
    Case("pptx_theme_dark", "docgen", _pptx_theme_dark),
    Case("pptx_all_layouts", "docgen", _pptx_all_layouts),
    Case("pptx_image_embed", "docgen", _pptx_image_embed),
    Case("pptx_diagram", "docgen", _pptx_diagram),
    Case("pptx_flow_autolayout", "docgen", _pptx_flow_autolayout),
    Case("pdf_image_embed", "docgen", _pdf_image_embed),
    Case("pdf_diagram", "docgen", _pdf_diagram),
    Case("docx_valid", "docgen", _docx_valid),
    Case("docx_image", "docgen", _docx_image),
    Case("xlsx_valid", "docgen", _xlsx_valid),
    Case("png_decode", "images", _png_decode),
    Case("render_pdf_to_png", "render", _render_pdf),
    Case("render_pptx_to_png", "render", _render_pptx),
    Case("studio_roundtrip", "studio", _studio_roundtrip),
    Case("studio_export_pdf", "studio", _studio_export_pdf),
]
