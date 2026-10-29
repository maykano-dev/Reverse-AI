"""Dependency-free, *designed* Excel (.xlsx) generator.

Produces a polished workbook with the standard library: a styled header row
(bold white text on an accent fill, centered, bordered), thin borders and subtle
banded fills on the body, sensible column widths, and a frozen header row. Uses
inline strings so no sharedStrings part is needed. Numbers stay numeric.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Any, Sequence

_ACCENT = "0A84FF"      # header fill
_BAND = "F2F7FF"        # subtle banded row fill
_HEADER_TEXT = "FFFFFF"
_BODY_TEXT = "1D1D1F"


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""

# Style indices (cellXfs): 0 default, 1 header, 2 body, 3 banded body.
_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2">
<font><sz val="11"/><color rgb="FF{_BODY_TEXT}"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FF{_HEADER_TEXT}"/><name val="Calibri"/></font>
</fonts>
<fills count="4">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF{_ACCENT}"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF{_BAND}"/></patternFill></fill>
</fills>
<borders count="2">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"><color rgb="FFD0D0D5"/></left><right style="thin"><color rgb="FFD0D0D5"/></right><top style="thin"><color rgb="FFD0D0D5"/></top><bottom style="thin"><color rgb="FFD0D0D5"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="4">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"/>
<xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFill="1" applyBorder="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _col_ref(idx: int) -> str:
    s = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        s = chr(65 + rem) + s
    return s


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _cell(col: int, row: int, value: Any, style: int) -> str:
    ref = f"{_col_ref(col)}{row}"
    s = f' s="{style}"' if style else ""
    if value is None or value == "":
        return f'<c r="{ref}"{s}/>'
    if _is_number(value):
        return f'<c r="{ref}"{s}><v>{value}</v></c>'
    return (f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">'
            f'{_esc(str(value))}</t></is></c>')


def _col_widths(rows: Sequence[Sequence[Any]]) -> str:
    widths: dict[int, int] = {}
    for row in rows:
        for c, v in enumerate(row):
            widths[c] = max(widths.get(c, 8), min(60, len(str(v)) + 3))
    if not widths:
        return ""
    cols = "".join(
        f'<col min="{c + 1}" max="{c + 1}" width="{w}" customWidth="1"/>'
        for c, w in sorted(widths.items()))
    return f"<cols>{cols}</cols>"


def render_xlsx(rows: Sequence[Sequence[Any]], sheet_name: str = "Sheet1") -> bytes:
    rows = [list(r) for r in rows] or [[]]
    has_header = len(rows) > 0 and any(str(v).strip() for v in rows[0])
    body = []
    for r, row in enumerate(rows, start=1):
        if r == 1 and has_header:
            style_for = lambda c: 1  # noqa: E731 - header
        else:
            banded = (r % 2 == 0)
            style_for = (lambda c, b=banded: 3 if b else 2)  # noqa: E731
        cells = "".join(_cell(c, r, v, style_for(c)) for c, v in enumerate(row))
        body.append(f'<row r="{r}">{cells}</row>')
    freeze = ('<sheetViews><sheetView workbookViewId="0">'
              '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
              '</sheetView></sheetViews>') if has_header else ""
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + freeze + _col_widths(rows) +
        '<sheetData>' + "".join(body) + '</sheetData></worksheet>')
    name = _esc(sheet_name)[:31] or "Sheet1"
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("xl/workbook.xml", _WORKBOOK.format(name=name))
        z.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        z.writestr("xl/styles.xml", _STYLES)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()
