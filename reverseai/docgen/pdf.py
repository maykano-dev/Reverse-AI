"""Minimal, dependency-free PDF writer.

Generates a valid multi-page PDF with a title and wrapped body text using the
built-in Helvetica font, so ReverseAI can hand back a real .pdf (a verification
report, an analysis write-up) with zero third-party packages. It is deliberately
small: headings, paragraphs, and bullet lines. For rich layout a later backend
can use reportlab when installed, but this always works.

The output is a correct PDF 1.4 file with a proper xref table and byte offsets,
which is what makes it actually open in viewers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# US Letter, 72dpi points.
_PAGE_W = 612
_PAGE_H = 792
_MARGIN = 72
_LEADING = 16          # body line height
_TITLE_SIZE = 20
_HEADING_SIZE = 14
_BODY_SIZE = 11
# Helvetica is ~0.5em average advance; good enough for wrapping at this size.
_CHARS_PER_LINE = 92


@dataclass
class _Block:
    kind: str          # "title" | "heading" | "body" | "bullet" | "space"
    text: str = ""


@dataclass
class PdfDoc:
    title: str = ""
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
    return (text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)"))


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        if len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def _content_lines(doc: PdfDoc) -> list[tuple[str, int, float]]:
    """Flatten blocks into (text, font_size, extra_gap_before) draw lines."""
    out: list[tuple[str, int, float]] = []
    if doc.title:
        for ln in _wrap(doc.title, _CHARS_PER_LINE):
            out.append((ln, _TITLE_SIZE, 0))
        out.append(("", _BODY_SIZE, 6))
    for b in doc.blocks:
        if b.kind == "space":
            out.append(("", _BODY_SIZE, 6))
        elif b.kind == "heading":
            out.append(("", _BODY_SIZE, 8))
            for ln in _wrap(b.text, _CHARS_PER_LINE):
                out.append((ln, _HEADING_SIZE, 0))
        elif b.kind == "bullet":
            wrapped = _wrap(b.text, _CHARS_PER_LINE - 2)
            for i, ln in enumerate(wrapped):
                out.append((("- " if i == 0 else "  ") + ln, _BODY_SIZE, 0))
        else:  # body
            for ln in _wrap(b.text, _CHARS_PER_LINE):
                out.append((ln, _BODY_SIZE, 0))
            out.append(("", _BODY_SIZE, 2))
    return out


def _paginate(lines: list[tuple[str, int, float]]) -> list[list[tuple[str, int, float]]]:
    pages: list[list[tuple[str, int, float]]] = []
    page: list[tuple[str, int, float]] = []
    y = _PAGE_H - _MARGIN
    for text, size, gap in lines:
        step = _LEADING + gap + (size - _BODY_SIZE) * 0.6
        if y - step < _MARGIN:
            pages.append(page)
            page = []
            y = _PAGE_H - _MARGIN
        page.append((text, size, gap))
        y -= step
    if page:
        pages.append(page)
    return pages or [[]]


def _page_stream(lines: list[tuple[str, int, float]]) -> bytes:
    parts = ["BT"]
    y = _PAGE_H - _MARGIN
    first = True
    for text, size, gap in lines:
        y -= gap
        if first:
            parts.append(f"/F1 {size} Tf")
            parts.append(f"{_MARGIN} {y:.1f} Td")
            first = False
        else:
            parts.append(f"/F1 {size} Tf")
            parts.append(f"0 {-(_LEADING + gap):.1f} Td")
        parts.append(f"({_esc(text)}) Tj")
        y -= _LEADING
    parts.append("ET")
    return ("\n".join(parts)).encode("latin-1", "replace")


def render_pdf(doc: PdfDoc) -> bytes:
    """Render a PdfDoc to valid PDF bytes."""
    pages = _paginate(_content_lines(doc))
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)   # 1-based object number

    # Reserve: catalog(1), pages(2), font(3), then per page: page + content.
    catalog_num, pages_num, font_num = 1, 2, 3
    objects.extend([b"", b"", b""])  # placeholders for 1..3

    page_obj_nums: list[int] = []
    for pg in pages:
        content = _page_stream(pg)
        stream = (b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
                  + content + b"\nendstream")
        content_num = add(stream)
        page_obj = (f"<< /Type /Page /Parent {pages_num} 0 R "
                    f"/MediaBox [0 0 {_PAGE_W} {_PAGE_H}] "
                    f"/Resources << /Font << /F1 {font_num} 0 R >> >> "
                    f"/Contents {content_num} 0 R >>").encode()
        page_num = add(page_obj)
        page_obj_nums.append(page_num)

    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objects[catalog_num - 1] = (f"<< /Type /Catalog /Pages {pages_num} 0 R >>").encode()
    objects[pages_num - 1] = (f"<< /Type /Pages /Kids [{kids}] "
                              f"/Count {len(page_obj_nums)} >>").encode()
    objects[font_num - 1] = (b"<< /Type /Font /Subtype /Type1 "
                             b"/BaseFont /Helvetica >>")

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
