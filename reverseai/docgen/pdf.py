"""Dependency-free, *designed* PDF writer.

Generates a valid multi-page PDF with real typographic hierarchy using the
built-in Helvetica family: a bold title with an accent rule, an optional
subtitle, section headings with a colored tick, justified-width body paragraphs,
and crisp vector bullets. Text is WinAnsi-encoded so bullets, dashes, and smart
quotes render in every viewer (not just ones that tolerate latin-1). No
third-party packages; the xref/offsets are written correctly.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field

_PAGE_W = 612
_PAGE_H = 792
_MARGIN = 64
_LEADING = 15.5
_TITLE_SIZE = 26
_SUBTITLE_SIZE = 13
_HEADING_SIZE = 15
_BODY_SIZE = 11
_CHARS_PER_LINE = 95

_ACCENT = (0.039, 0.518, 1.0)     # #0A84FF
_INK = (0.102, 0.102, 0.11)       # #1A1A1C
_DIM = (0.44, 0.44, 0.47)
_K = 0.5523                        # circle Bezier constant


@dataclass
class _Line:
    text: str
    size: float
    gap: float = 0.0              # extra space above this line
    bold: bool = False
    color: tuple = _INK
    rule: bool = False            # accent rule under this line (title)
    bullet: bool = False          # draw a vector bullet dot to the left
    tick: bool = False            # draw a short accent tick to the left (heading)
    indent: float = 0.0


@dataclass
class _Block:
    kind: str
    text: str = ""
    image: object = None          # DecodedImage for kind == "image"
    width: float = 0.0            # requested image width in points (0 = auto)
    shapes: list = field(default_factory=list)   # for kind == "diagram"
    height: float = 240.0         # diagram height in points


@dataclass
class _Img:
    """A laid-out image in the content flow."""
    image: object
    w: float
    h: float
    caption: str = ""
    gap: float = 14.0


@dataclass
class _Diagram:
    """A laid-out diagram (shape primitives) in the content flow."""
    shapes: list
    h: float = 240.0
    gap: float = 16.0


@dataclass
class PdfDoc:
    title: str = ""
    subtitle: str = ""
    blocks: list[_Block] = field(default_factory=list)

    def heading(self, text: str) -> "PdfDoc":
        self.blocks.append(_Block("heading", text))
        return self

    def paragraph(self, text: str) -> "PdfDoc":
        self.blocks.append(_Block("body", text))
        return self

    def bullet(self, text: str) -> "PdfDoc":
        self.blocks.append(_Block("bullet", text))
        return self

    def image(self, decoded, caption: str = "", width: float = 0.0) -> "PdfDoc":
        self.blocks.append(_Block("image", text=caption, image=decoded, width=width))
        return self

    def diagram(self, shapes, height: float = 240.0) -> "PdfDoc":
        b = _Block("diagram")
        b.shapes = list(shapes or [])
        b.height = float(height or 240.0)
        self.blocks.append(b)
        return self

    def space(self) -> "PdfDoc":
        self.blocks.append(_Block("space"))
        return self


def _esc(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _enc(text: str) -> bytes:
    # WinAnsi (cp1252) so U+2022 bullet, em dash, smart quotes etc. survive.
    return _esc(text).encode("cp1252", "replace")


def _wrap(text: str, width: int) -> list[str]:
    words = str(text).split()
    if not words:
        return [""]
    lines, cur = [], words[0]
    for w in words[1:]:
        if len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _lines(doc: PdfDoc) -> list[_Line]:
    out: list[_Line] = []
    if doc.title:
        wrapped = _wrap(doc.title, 42)
        for i, ln in enumerate(wrapped):
            out.append(_Line(ln, _TITLE_SIZE, 0, bold=True, color=_INK,
                             rule=(i == len(wrapped) - 1)))
    if doc.subtitle:
        for i, ln in enumerate(_wrap(doc.subtitle, 70)):
            out.append(_Line(ln, _SUBTITLE_SIZE, 16 if i == 0 else 2, color=_DIM))
    out.append(_Line("", _BODY_SIZE, 10))
    content_w = _PAGE_W - 2 * _MARGIN
    max_h = _PAGE_H - 2 * _MARGIN - 40
    for b in doc.blocks:
        if b.kind == "space":
            out.append(_Line("", _BODY_SIZE, 8))
        elif b.kind == "image" and b.image is not None:
            iw, ih = float(b.image.width), float(b.image.height)
            w = b.width or content_w
            w = min(w, content_w)
            h = w * (ih / iw) if iw else 0
            if h > max_h:  # keep it on one page
                h = max_h
                w = h * (iw / ih) if ih else w
            out.append(_Img(image=b.image, w=w, h=h, caption=b.text or ""))
        elif b.kind == "diagram":
            out.append(_Diagram(shapes=b.shapes, h=min(float(b.height or 240), max_h)))
        elif b.kind == "heading":
            first = True
            for ln in _wrap(b.text, 60):
                out.append(_Line(ln, _HEADING_SIZE, 14 if first else 0,
                                 bold=True, color=_INK, tick=first, indent=12))
                first = False
            out.append(_Line("", _BODY_SIZE, 3))
        elif b.kind == "bullet":
            wrapped = _wrap(b.text, _CHARS_PER_LINE - 6)
            for i, ln in enumerate(wrapped):
                out.append(_Line(ln, _BODY_SIZE, 3 if i == 0 else 0,
                                 bullet=(i == 0), indent=18))
        else:
            for ln in _wrap(b.text, _CHARS_PER_LINE):
                out.append(_Line(ln, _BODY_SIZE))
            out.append(_Line("", _BODY_SIZE, 4))
    return out


def _step(ln) -> float:
    if isinstance(ln, _Img):
        return ln.gap + ln.h + (16 if ln.caption else 0) + 6
    if isinstance(ln, _Diagram):
        return ln.gap + ln.h + 8
    return _LEADING + ln.gap + (ln.size - _BODY_SIZE) * 0.62


def _paginate(lines) -> list[list]:
    pages, page = [], []
    y = _PAGE_H - _MARGIN
    for ln in lines:
        step = _step(ln)
        if y - step < _MARGIN and page:
            pages.append(page)
            page, y = [], _PAGE_H - _MARGIN
        page.append(ln)
        y -= step
    if page:
        pages.append(page)
    return pages or [[]]


def _text_w(text: str, size: float) -> float:
    return len(text) * size * 0.5          # rough Helvetica average advance


def _circle(cx: float, cy: float, r: float) -> str:
    k = _K * r
    return (f"{cx - r:.2f} {cy:.2f} m "
            f"{cx - r:.2f} {cy + k:.2f} {cx - k:.2f} {cy + r:.2f} {cx:.2f} {cy + r:.2f} c "
            f"{cx + k:.2f} {cy + r:.2f} {cx + r:.2f} {cy + k:.2f} {cx + r:.2f} {cy:.2f} c "
            f"{cx + r:.2f} {cy - k:.2f} {cx + k:.2f} {cy - r:.2f} {cx:.2f} {cy - r:.2f} c "
            f"{cx - k:.2f} {cy - r:.2f} {cx - r:.2f} {cy - k:.2f} {cx - r:.2f} {cy:.2f} c f")


def _ellipse(cx: float, cy: float, rx: float, ry: float) -> str:
    kx, ky = _K * rx, _K * ry
    return (f"{cx - rx:.2f} {cy:.2f} m "
            f"{cx - rx:.2f} {cy + ky:.2f} {cx - kx:.2f} {cy + ry:.2f} {cx:.2f} {cy + ry:.2f} c "
            f"{cx + kx:.2f} {cy + ry:.2f} {cx + rx:.2f} {cy + ky:.2f} {cx + rx:.2f} {cy:.2f} c "
            f"{cx + rx:.2f} {cy - ky:.2f} {cx + kx:.2f} {cy - ry:.2f} {cx:.2f} {cy - ry:.2f} c "
            f"{cx - kx:.2f} {cy - ry:.2f} {cx - rx:.2f} {cy - ky:.2f} {cx - rx:.2f} {cy:.2f} c f")


def _rgb(c, default):
    s = str(c or "").lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) == 6:
        try:
            return (int(s[0:2], 16) / 255, int(s[2:4], 16) / 255, int(s[4:6], 16) / 255)
        except ValueError:
            pass
    return default


def _diagram_ops(shapes, left, top, w, h):
    """Return (vector_ops, text_ops) for a diagram area. Coords are 0..100."""
    vec, txt = [], []

    def X(v): return left + (float(v) / 100.0) * w
    def Yt(v): return top - (float(v) / 100.0) * h      # from the top, going down
    def Wd(v): return (float(v) / 100.0) * w
    def Hd(v): return (float(v) / 100.0) * h

    for sh in shapes or []:
        if not isinstance(sh, dict):
            continue
        kind = str(sh.get("type") or "rect").lower()
        col = _rgb(sh.get("color"), _ACCENT)
        cs = f"{col[0]:.3f} {col[1]:.3f} {col[2]:.3f}"
        if kind in ("rect", "roundrect", "ellipse"):
            x, ytop = X(sh.get("x", 0)), Yt(sh.get("y", 0))
            bw, bh = Wd(sh.get("w", 20)), Hd(sh.get("h", 18))
            yb = ytop - bh
            if kind == "ellipse":
                vec.append(f"{cs} rg " + _ellipse(x + bw / 2, yb + bh / 2, bw / 2, bh / 2))
            else:
                vec.append(f"{cs} rg {x:.1f} {yb:.1f} {bw:.1f} {bh:.1f} re f")
            if sh.get("text"):
                tc = _rgb(sh.get("text_color"), (1, 1, 1))
                size = 11
                tw = _text_w(str(sh["text"]), size)
                tx = x + (bw - tw) / 2
                ty = yb + bh / 2 - size * 0.34
                txt.append(f"{tc[0]:.3f} {tc[1]:.3f} {tc[2]:.3f} rg")
                txt.append(f"/F2 {size} Tf")
                txt.append(f"1 0 0 1 {max(x, tx):.1f} {ty:.1f} Tm")
                txt.append(f"({_esc(str(sh['text']))}) Tj")
        elif kind in ("line", "arrow"):
            x1, y1 = X(sh.get("x", 0)), Yt(sh.get("y", 0))
            x2, y2 = X(sh.get("x2", sh.get("x", 0))), Yt(sh.get("y2", sh.get("y", 0)))
            vec.append(f"{cs} RG 1.6 w {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S")
            if kind == "arrow":
                ang = math.atan2(y2 - y1, x2 - x1)
                a = 6.5
                p2x, p2y = x2 - a * math.cos(ang - 0.42), y2 - a * math.sin(ang - 0.42)
                p3x, p3y = x2 - a * math.cos(ang + 0.42), y2 - a * math.sin(ang + 0.42)
                vec.append(f"{cs} rg {x2:.1f} {y2:.1f} m {p2x:.1f} {p2y:.1f} l "
                           f"{p3x:.1f} {p3y:.1f} l f")
        elif kind == "text":
            tc = _rgb(sh.get("color"), _INK)
            size = int(sh.get("size") or 13)
            txt.append(f"{tc[0]:.3f} {tc[1]:.3f} {tc[2]:.3f} rg")
            txt.append(f"/F1 {size} Tf")
            txt.append(f"1 0 0 1 {X(sh.get('x', 0)):.1f} {Yt(sh.get('y', 0)) - size:.1f} Tm")
            txt.append(f"({_esc(str(sh.get('text', '')))}) Tj")
    return vec, txt


def _page_stream(lines) -> tuple[bytes, list]:
    text_parts = ["BT"]
    vec_parts: list[str] = []
    img_parts: list[str] = []
    imgs: list = []            # DecodedImage in draw order -> Im0, Im1, ...
    content_w = _PAGE_W - 2 * _MARGIN
    y = _PAGE_H - _MARGIN
    last_color = None
    a = _ACCENT
    for ln in lines:
        if isinstance(ln, _Diagram):
            y -= ln.gap
            dv, dt = _diagram_ops(ln.shapes, _MARGIN, y, content_w, ln.h)
            vec_parts.extend(dv)
            text_parts.extend(dt)
            last_color = None
            y = y - ln.h - 8
            continue
        if isinstance(ln, _Img):
            y -= ln.gap
            top = y
            x = _MARGIN + (content_w - ln.w) / 2
            ybl = top - ln.h
            name = f"Im{len(imgs)}"
            imgs.append(ln.image)
            img_parts.append(f"q {ln.w:.2f} 0 0 {ln.h:.2f} {x:.2f} {ybl:.2f} cm /{name} Do Q")
            if ln.caption:
                cap_base = ybl - 12
                cx = _MARGIN + (content_w - _text_w(ln.caption, 9.5)) / 2
                text_parts.append(f"{_DIM[0]} {_DIM[1]} {_DIM[2]} rg")
                last_color = _DIM
                text_parts.append(f"/F1 9.5 Tf")
                text_parts.append(f"1 0 0 1 {max(_MARGIN, cx):.1f} {cap_base:.1f} Tm")
                text_parts.append(f"({_esc(ln.caption)}) Tj")
            y = ybl - (16 if ln.caption else 0) - 6
            continue
        y -= ln.gap
        baseline = y - ln.size * 0.80
        if ln.text:
            if ln.color != last_color:
                text_parts.append(f"{ln.color[0]} {ln.color[1]} {ln.color[2]} rg")
                last_color = ln.color
            font = "F2" if ln.bold else "F1"
            x = _MARGIN + ln.indent
            text_parts.append(f"/{font} {ln.size:g} Tf")
            text_parts.append(f"1 0 0 1 {x:.1f} {baseline:.1f} Tm")
            text_parts.append(f"({_esc(ln.text)}) Tj")
        if ln.bullet:
            vec_parts.append(f"{a[0]} {a[1]} {a[2]} rg "
                             + _circle(_MARGIN + 6, baseline + ln.size * 0.28, 2.0))
        if ln.tick:
            ty = baseline - 1
            vec_parts.append(f"{a[0]} {a[1]} {a[2]} rg "
                             f"{_MARGIN:.1f} {ty:.1f} 3 {ln.size:.1f} re f")
        if ln.rule:
            ry = baseline - 8
            vec_parts.append(f"{a[0]} {a[1]} {a[2]} RG 1.4 w "
                             f"{_MARGIN} {ry:.1f} m {_PAGE_W - _MARGIN} {ry:.1f} l S")
        y -= _LEADING + (ln.size - _BODY_SIZE) * 0.62
    text_parts.append("ET")
    # Images and vector marks first, then text on top.
    body = "\n".join(img_parts + vec_parts + text_parts)
    out = bytearray()
    for part in body.split("\n"):
        if part.endswith(" Tj") and "(" in part:
            head, rest = part.split("(", 1)
            inner = rest[:-len(") Tj")]  # strip ") Tj"
            out += head.encode("ascii") + b"(" + inner.encode("cp1252", "replace") + b") Tj\n"
        else:
            out += part.encode("ascii", "replace") + b"\n"
    return bytes(out), imgs


def _image_object(decoded) -> bytes:
    """Build an Image XObject stream for a DecodedImage."""
    w, h = int(decoded.width), int(decoded.height)
    if decoded.fmt == "jpeg":
        body = decoded.data
        filt = b"/DCTDecode"
    else:  # raw RGB -> Flate-compress
        body = zlib.compress(decoded.data, 6)
        filt = b"/FlateDecode"
    header = (f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} "
              f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter ".encode()
              + filt + f" /Length {len(body)} >>".encode())
    return header + b"\nstream\n" + body + b"\nendstream"


def render_pdf(doc: PdfDoc) -> bytes:
    pages = _paginate(_lines(doc))
    objects: list[bytes] = [b"", b"", b"", b""]  # catalog, pages, F1, F2
    catalog_num, pages_num, f1_num, f2_num = 1, 2, 3, 4

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    page_nums = []
    for pg in pages:
        content, imgs = _page_stream(pg)
        stream = (b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
                  + content + b"\nendstream")
        content_num = add(stream)
        xobj_entries = []
        for k, decoded in enumerate(imgs):
            img_num = add(_image_object(decoded))
            xobj_entries.append(f"/Im{k} {img_num} 0 R")
        xobj_res = (" /XObject << " + " ".join(xobj_entries) + " >>") if xobj_entries else ""
        page_obj = (f"<< /Type /Page /Parent {pages_num} 0 R "
                    f"/MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
                    f"/Resources << /Font << /F1 {f1_num} 0 R /F2 {f2_num} 0 R >>{xobj_res} >> "
                    f"/Contents {content_num} 0 R >>").encode()
        page_nums.append(add(page_obj))

    kids = " ".join(f"{n} 0 R" for n in page_nums)
    objects[0] = f"<< /Type /Catalog /Pages {pages_num} 0 R >>".encode()
    objects[1] = (f"<< /Type /Pages /Kids [{kids}] /Count {len(page_nums)} >>").encode()
    enc = b" /Encoding /WinAnsiEncoding"
    objects[2] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica" + enc + b" >>"
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold" + enc + b" >>"

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (len(objects) + 1)
    for i, obj in enumerate(objects, start=1):
        offsets[i] = len(out)
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for i in range(1, len(objects) + 1):
        out += f"{offsets[i]:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_num} 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode()
    return bytes(out)
