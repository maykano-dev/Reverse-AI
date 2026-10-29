"""Dependency-free Word (.docx) generator.

Writes the minimal OOXML a .docx needs (content types, root rels, and
word/document.xml) so ReverseAI can hand back a real, editable Word document
with no third-party packages: headings, paragraphs, and bullet lines.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from io import BytesIO


@dataclass
class _Block:
    kind: str          # "heading" | "body" | "bullet"
    text: str = ""
    level: int = 1


@dataclass
class DocxDoc:
    title: str = ""
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


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def _run(text: str, *, bold: bool = False, size: int | None = None) -> str:
    props = []
    if bold:
        props.append("<w:b/>")
    if size:
        props.append(f'<w:sz w:val="{size * 2}"/>')  # half-points
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    return f"<w:r>{rpr}<w:t xml:space=\"preserve\">{_esc(text)}</w:t></w:r>"


def _para(content: str, *, style: str | None = None, bullet: bool = False) -> str:
    ppr = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if bullet:
        ppr.append('<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>')
    ppr_xml = f"<w:pPr>{''.join(ppr)}</w:pPr>" if ppr else ""
    return f"<w:p>{ppr_xml}{content}</w:p>"


def render_docx(doc: DocxDoc) -> bytes:
    body = []
    if doc.title:
        body.append(_para(_run(doc.title, bold=True, size=24)))
    for b in doc.blocks:
        if b.kind == "heading":
            body.append(_para(_run(b.text, bold=True, size=16)))
        elif b.kind == "bullet":
            # Plain bullet via a leading dash keeps it valid without numbering.xml.
            body.append(_para(_run("•  " + b.text)))
        else:
            body.append(_para(_run(b.text)))
    if not body:
        body.append(_para(_run("")))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:body>' + "".join(body) +
        '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
        '</w:sectPr></w:body></w:document>')
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("word/document.xml", document)
    return buf.getvalue()
