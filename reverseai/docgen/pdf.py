"""Dependency-free, *designed* PDF writer.

Generates a valid multi-page PDF with real typographic hierarchy using the
built-in Helvetica family: a bold accent title with a rule under it, an optional
subtitle, bold section headings, body paragraphs, and bullet lines, all with
sensible spacing and color. No third-party packages; the xref/offsets are
written correctly so it opens in any viewer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_PAGE_W = 612
_PAGE_H = 792
_MARGIN = 72
_LEADING = 15
_TITLE_SIZE = 22
_SUBTITLE_SIZE = 13
_HEADING_SIZE = 14
_BODY_SIZE = 11
_CHARS_PER_LINE = 92

_ACCENT = (0.039, 0.518, 1.0)     # #0A84FF
_INK = (0.114, 0.114, 0.122)      # #1D1D1F
_DIM = (0.43, 0.43, 0.45)


@dataclass
class _Line:
    text: str
    size: int
    gap: float = 0.0
    bold: bool = False
    color: tuple = _INK
    rule: bool = False            # draw a thin accent rule under this line


@dataclass
class _Block:
    kind: str
    text: str = ""


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

    def space(self) -> "PdfDoc":
        self.blocks.append(_Block("space"))
        return self


def _esc(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
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
        wrapped = _wrap(doc.title, _CHARS_PER_LINE)
        for i, ln in enumerate(wrapped):
            out.append(_Line(ln, _TITLE_SIZE, 0, bold=True, color=_INK,
                             rule=(i == len(wrapped) - 1)))
    if doc.subtitle:
        for ln in _wrap(doc.subtitle, _CHARS_PER_LINE):
            out.append(_Line(ln, _SUBTITLE_SIZE, 2, color=_DIM))
    out.append(_Line("", _BODY_SIZE, 6))
    for b in doc.blocks:
        if b.kind == "space":
            out.append(_Line("", _BODY_SIZE, 6))
        elif b.kind == "heading":
            out.append(_Line("", _BODY_SIZE, 8))
            for ln in _wrap(b.text, _CHARS_PER_LINE):
                out.append(_Line(ln, _HEADING_SIZE, 0, bold=True, color=_ACCENT))
        elif b.kind == "bullet":
            wrapped = _wrap(b.text, _CHARS_PER_LINE - 2)
            for i, ln in enumerate(wrapped):
                out.append(_Line(("•  " if i == 0 else "   ") + ln, _BODY_SIZE))
        else:
            for ln in _wrap(b.text, _CHARS_PER_LINE):
                out.append(_Line(ln, _BODY_SIZE))
            out.append(_Line("", _BODY_SIZE, 2))
    return out


def _paginate(lines: list[_Line]) -> list[list[_Line]]:
    pages, page = [], []
    y = _PAGE_H - _MARGIN
    for ln in lines:
        step = _LEADING + ln.gap + (ln.size - _BODY_SIZE) * 0.6
        if y - step < _MARGIN:
            pages.append(page)
            page, y = [], _PAGE_H - _MARGIN
        page.append(ln)
        y -= step
    if page:
        pages.append(page)
    return pages or [[]]


def _page_stream(lines: list[_Line]) -> bytes:
    parts, rules = ["BT"], []
    y = _PAGE_H - _MARGIN
    last = _INK
    parts.append(f"{last[0]} {last[1]} {last[2]} rg")
    first = True
    for ln in lines:
        y -= ln.gap
        if ln.color != last:
            parts.append(f"{ln.color[0]} {ln.color[1]} {ln.color[2]} rg")
            last = ln.color
        font = "F2" if ln.bold else "F1"
        if first:
            parts.append(f"/{font} {ln.size} Tf")
            parts.append(f"{_MARGIN} {y:.1f} Td")
            first = False
        else:
            parts.append(f"/{font} {ln.size} Tf")
            parts.append(f"0 {-(_LEADING + ln.gap):.1f} Td")
        parts.append(f"({_esc(ln.text)}) Tj")
        y -= _LEADING
        if ln.rule:
            rules.append(y + 6)
    parts.append("ET")
    for ry in rules:
        parts.append(f"{_ACCENT[0]} {_ACCENT[1]} {_ACCENT[2]} RG 1.2 w "
                     f"{_MARGIN} {ry:.1f} m {_PAGE_W - _MARGIN} {ry:.1f} l S")
    return ("\n".join(parts)).encode("latin-1", "replace")


def render_pdf(doc: PdfDoc) -> bytes:
    pages = _paginate(_lines(doc))
    objects: list[bytes] = [b"", b"", b"", b""]  # catalog, pages, F1, F2
    catalog_num, pages_num, f1_num, f2_num = 1, 2, 3, 4

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    page_nums = []
    for pg in pages:
        content = _page_stream(pg)
        stream = (b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
                  + content + b"\nendstream")
        content_num = add(stream)
        page_obj = (f"<< /Type /Page /Parent {pages_num} 0 R "
                    f"/MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
                    f"/Resources << /Font << /F1 {f1_num} 0 R /F2 {f2_num} 0 R >> >> "
                    f"/Contents {content_num} 0 R >>").encode()
        page_nums.append(add(page_obj))

    kids = " ".join(f"{n} 0 R" for n in page_nums)
    objects[0] = f"<< /Type /Catalog /Pages {pages_num} 0 R >>".encode()
    objects[1] = (f"<< /Type /Pages /Kids [{kids}] /Count {len(page_nums)} >>").encode()
    objects[2] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"

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
