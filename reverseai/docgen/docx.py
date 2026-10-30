"""Dependency-free, *designed* Word (.docx) generator.

Produces a polished document with the standard library: a real Title style, two
Heading levels in an accent color, proper bullet lists (via numbering.xml, not a
dash hack), comfortable spacing, and optional tables with a shaded header row.
No third-party packages.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Sequence

_ACCENT = "0A84FF"
_INK = "1D1D1F"


@dataclass
class _Block:
    kind: str                     # heading | body | bullet | table | subtitle | image
    text: str = ""
    level: int = 1
    rows: list[list[Any]] = field(default_factory=list)
    data: bytes = b""             # image bytes for kind == "image"
    img_w: int = 0
    img_h: int = 0


@dataclass
class DocxDoc:
    title: str = ""
    subtitle: str = ""
    blocks: list[_Block] = field(default_factory=list)

    def heading(self, text: str, level: int = 1) -> "DocxDoc":
        self.blocks.append(_Block("heading", text, level))
        return self

    def paragraph(self, text: str) -> "DocxDoc":
        self.blocks.append(_Block("body", text))
        return self

    def bullet(self, text: str) -> "DocxDoc":
        self.blocks.append(_Block("bullet", text))
        return self

    def table(self, rows: Sequence[Sequence[Any]]) -> "DocxDoc":
        self.blocks.append(_Block("table", rows=[list(r) for r in rows]))
        return self

    def image(self, data: bytes, img_w: int, img_h: int, caption: str = "") -> "DocxDoc":
        self.blocks.append(_Block("image", text=caption, data=bytes(data),
                                  img_w=int(img_w), img_h=int(img_h)))
        return self


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="jpg" ContentType="image/jpeg"/>
<Default Extension="jpeg" ContentType="image/jpeg"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
</Relationships>"""

_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/><w:color w:val="{_INK}"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:pPr><w:spacing w:before="0" w:after="120"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri Light" w:hAnsi="Calibri Light"/><w:b/><w:color w:val="{_INK}"/><w:sz w:val="56"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:pPr><w:spacing w:after="320"/></w:pPr><w:rPr><w:color w:val="6E6E73"/><w:sz w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="320" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:color w:val="{_ACCENT}"/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:color w:val="{_INK}"/><w:sz w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr><w:spacing w:after="60"/></w:pPr></w:style>
</w:styles>"""

_NUMBERING = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="&#8226;"/><w:lvlJc w:val="left"/><w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr></w:lvl></w:abstractNum>
<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>
</w:numbering>"""


def _run(text: str, *, bold: bool = False, color: str | None = None,
         size: int | None = None) -> str:
    props = []
    if bold:
        props.append("<w:b/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    if size:
        props.append(f'<w:sz w:val="{size}"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{_esc(text)}</w:t></w:r>'


def _para(content: str, *, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{content}</w:p>"


def _table(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    cols = max(len(r) for r in rows)
    grid = "".join('<w:gridCol w:w="2600"/>' for _ in range(cols))
    body = []
    for ri, row in enumerate(rows):
        cells = []
        for ci in range(cols):
            val = row[ci] if ci < len(row) else ""
            is_head = ri == 0
            shade = (f'<w:shd w:val="clear" w:fill="{_ACCENT}"/>'
                     if is_head else
                     (f'<w:shd w:val="clear" w:fill="F2F7FF"/>' if ri % 2 else ""))
            run = _run(str(val), bold=is_head,
                       color=("FFFFFF" if is_head else None))
            cells.append(
                f'<w:tc><w:tcPr><w:tcW w:w="2600" w:type="dxa"/>{shade}'
                f'<w:tcMar><w:top w:w="60" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/>'
                f'<w:left w:w="100" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tcMar>'
                f'</w:tcPr><w:p>{run}</w:p></w:tc>')
        body.append(f"<w:tr>{''.join(cells)}</w:tr>")
    borders = ('<w:tblBorders>'
               + "".join(f'<w:{s} w:val="single" w:sz="4" w:color="D0D0D5"/>'
                         for s in ("top", "left", "bottom", "right",
                                   "insideH", "insideV"))
               + '</w:tblBorders>')
    return (f'<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>{borders}</w:tblPr>'
            f'<w:tblGrid>{grid}</w:tblGrid>{"".join(body)}</w:tbl>'
            '<w:p/>')


_MAX_IMG_EMU = 5486400       # ~6 inches, the content width at 1in margins
_EMU_PER_PX = 9525


def _img_ext(data: bytes) -> str:
    return "png" if data[:4] == b"\x89PNG" else "jpg"


def _drawing(rid: str, did: int, w_px: int, h_px: int) -> str:
    cx = min(w_px * _EMU_PER_PX, _MAX_IMG_EMU) if w_px else _MAX_IMG_EMU
    cy = int(cx * (h_px / w_px)) if w_px and h_px else int(cx * 0.6)
    cx = int(cx)
    return (
        '<w:p><w:r><w:drawing>'
        '<wp:inline distT="0" distB="0" distL="0" distR="0" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{did}" name="Picture {did}"/>'
        '<wp:cNvGraphicFramePr><a:graphicFrameLocks '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'noChangeAspect="1"/></wp:cNvGraphicFramePr>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:nvPicPr><pic:cNvPr id="{did}" name="img{did}"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>')


def render_docx(doc: DocxDoc) -> bytes:
    body = []
    media = []       # (filename, bytes)
    img_rels = []    # (rid, filename)
    if doc.title:
        body.append(_para(_run(doc.title), style="Title"))
    if doc.subtitle:
        body.append(_para(_run(doc.subtitle), style="Subtitle"))
    for b in doc.blocks:
        if b.kind == "heading":
            body.append(_para(_run(b.text),
                              style="Heading2" if b.level >= 2 else "Heading1"))
        elif b.kind == "bullet":
            body.append(_para(_run(b.text), style="ListBullet"))
        elif b.kind == "table":
            body.append(_table(b.rows))
        elif b.kind == "image" and b.data:
            n = len(media) + 1
            ext = _img_ext(bytes(b.data))
            fname = f"image{n}.{ext}"
            rid = f"rIdImg{n}"
            media.append((fname, bytes(b.data)))
            img_rels.append((rid, fname))
            body.append(_drawing(rid, 100 + n, b.img_w, b.img_h))
            if b.text:
                body.append(_para(_run(b.text, color="6E6E73", size=18)))
        else:
            body.append(_para(_run(b.text)))
    if not body:
        body.append(_para(_run("")))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<w:body>' + "".join(body) +
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
        '</w:sectPr></w:body></w:document>')
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
        + "".join(f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
                  f'officeDocument/2006/relationships/image" Target="media/{fname}"/>'
                  for rid, fname in img_rels)
        + '</Relationships>')
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("word/numbering.xml", _NUMBERING)
        for fname, data in media:
            z.writestr(f"word/media/{fname}", data)
    return buf.getvalue()
