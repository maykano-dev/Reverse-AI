"""Dependency-free, *designed* PowerPoint (.pptx) generator.

A .pptx is a ZIP of OOXML parts. This builds real, editable decks with design,
not just white slides with black text:

  * Theme palettes (light, midnight, aurora, sunset, forest, mono) or fully
    custom colors; per-slide background overrides, including dark backgrounds.
  * Chosen title/body fonts.
  * Layouts: cover (title), section divider, content (bulleted), two-column,
    quote, and statement.
  * Decorative shapes: accent bars under titles, corner accents, big soft
    background shapes - drawn as native DrawingML so they stay editable.
  * Colored bullets.

Slides are composed from absolutely positioned shapes so we control the whole
design, while the master/layout stay minimal and valid. No third-party packages.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from io import BytesIO

# 16:9 widescreen, in EMU (914400 EMU per inch): 13.333in x 7.5in.
_W = 12192000
_H = 6858000
_IN = 914400
_MARGIN = 823912          # ~0.9in


# --------------------------------------------------------------------------- #
# palette & fonts
# --------------------------------------------------------------------------- #
PRESETS = {
    "light":    dict(bg="FFFFFF", surface="F3F5F9", ink="16181D", muted="5C6672",
                     accent="2D6CDF", accent2="7C5CFF", on_accent="FFFFFF"),
    "midnight": dict(bg="0E1526", surface="18233E", ink="EEF3FF", muted="9DB2D6",
                     accent="4F8CFF", accent2="C98BFF", on_accent="FFFFFF"),
    "aurora":   dict(bg="07121A", surface="0E2230", ink="EAFBFF", muted="8FC7D6",
                     accent="2AD6B5", accent2="4FA6FF", on_accent="04221C"),
    "sunset":   dict(bg="1C1020", surface="2C1630", ink="FFF0EC", muted="E3A6B8",
                     accent="FF6B4A", accent2="FFB24A", on_accent="2A0C08"),
    "forest":   dict(bg="0C1A12", surface="12271B", ink="ECFBEF", muted="97C4A6",
                     accent="35C06A", accent2="9BD94F", on_accent="05240F"),
    "mono":     dict(bg="121316", surface="1D1F24", ink="F4F5F7", muted="A2A7B0",
                     accent="E8EAED", accent2="9AA0AA", on_accent="121316"),
    "slate":    dict(bg="F7F8FA", surface="FFFFFF", ink="1B2230", muted="5A6676",
                     accent="4457F2", accent2="12B5A5", on_accent="FFFFFF"),
}
_DEFAULT_FONTS = {"title": "Georgia", "body": "Helvetica Neue"}


def _hex(c: str, fallback: str) -> str:
    s = str(c or "").lstrip("#").strip().upper()
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) == 6 and all(ch in "0123456789ABCDEF" for ch in s):
        return s
    return fallback


def resolve_theme(theme) -> dict:
    """A theme is a preset name, or a dict of colors/fonts, or None."""
    base = dict(PRESETS["light"])
    base["fonts"] = dict(_DEFAULT_FONTS)
    if isinstance(theme, str):
        base.update(PRESETS.get(theme.lower(), {}))
        base["fonts"] = dict(_DEFAULT_FONTS)
    elif isinstance(theme, dict):
        preset = theme.get("preset")
        if isinstance(preset, str) and preset.lower() in PRESETS:
            base.update(PRESETS[preset.lower()])
        for k in ("bg", "surface", "ink", "muted", "accent", "accent2", "on_accent"):
            if theme.get(k):
                base[k] = _hex(theme[k], base[k])
        fonts = theme.get("fonts") or {}
        base["fonts"] = {
            "title": str(fonts.get("title") or _DEFAULT_FONTS["title"]),
            "body": str(fonts.get("body") or _DEFAULT_FONTS["body"]),
        }
    # normalize all colors
    for k in ("bg", "surface", "ink", "muted", "accent", "accent2", "on_accent"):
        base[k] = _hex(base[k], PRESETS["light"][k])
    base.setdefault("fonts", dict(_DEFAULT_FONTS))
    return base


@dataclass
class Slide:
    title: str = ""
    bullets: list[str] = field(default_factory=list)
    subtitle: str = ""
    layout: str = ""                 # cover|section|content|two-column|quote|statement
    columns: list = field(default_factory=list)   # [[...],[...]] for two-column
    quote: str = ""
    attribution: str = ""
    bg: str = ""                     # per-slide background override (hex)
    accent: str = ""                 # per-slide accent override (hex)
    notes: str = ""

    def effective_layout(self) -> str:
        if self.layout:
            return self.layout.lower()
        if self.quote:
            return "quote"
        if self.columns:
            return "two-column"
        if not self.bullets and self.subtitle:
            return "cover"
        return "content"


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _pt(n: float) -> int:
    return int(round(n * 100))        # OOXML font size unit = 1/100 pt


# --------------------------------------------------------------------------- #
# shape helpers
# --------------------------------------------------------------------------- #
def _rect(sid, name, x, y, w, h, fill_hex, alpha=None, geom="rect", round_val=None):
    fill = (f'<a:solidFill><a:srgbClr val="{fill_hex}">'
            + (f'<a:alpha val="{alpha}"/>' if alpha is not None else "")
            + '</a:srgbClr></a:solidFill>')
    av = (f'<a:gd name="adj" fmla="val {round_val}"/>' if round_val is not None else "")
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{name}"/><p:cNvSpPr/>'
            f'<p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{int(x)}" y="{int(y)}"/>'
            f'<a:ext cx="{int(w)}" cy="{int(h)}"/></a:xfrm>'
            f'<a:prstGeom prst="{geom}"><a:avLst>{av}</a:avLst></a:prstGeom>'
            f'{fill}<a:ln><a:noFill/></a:ln></p:spPr>'
            f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:endParaRPr lang="en-US"/>'
            f'</a:p></p:txBody></p:sp>')


def _run(text, size, color, font, bold=False, italic=False, spc=None):
    sp = f' spc="{spc}"' if spc is not None else ""
    it = ' i="1"' if italic else ""
    return (f'<a:r><a:rPr lang="en-US" sz="{_pt(size)}" b="{1 if bold else 0}"{it}{sp}>'
            f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            f'<a:latin typeface="{_esc(font)}"/></a:rPr><a:t>{_esc(text)}</a:t></a:r>')


def _para(runs, algn="l", marL=None, indent=None, bu_color=None, bu_char=None,
          space_after=600):
    ppr_bits = f' algn="{algn}"'
    if marL is not None:
        ppr_bits += f' marL="{marL}" indent="{indent or 0}"'
    inner = f'<a:spcAft><a:spcPts val="{space_after}"/></a:spcAft>'
    if bu_char is not None:
        inner += (f'<a:buClr><a:srgbClr val="{bu_color}"/></a:buClr>'
                  f'<a:buSzPct val="90000"/><a:buChar char="{bu_char}"/>')
    else:
        inner += '<a:buNone/>'
    return f'<a:p><a:pPr{ppr_bits}>{inner}</a:pPr>{runs}</a:p>'


def _textbox(sid, name, x, y, w, h, paras, anchor="t"):
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{name}"/>'
            f'<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr>'
            f'<a:xfrm><a:off x="{int(x)}" y="{int(y)}"/>'
            f'<a:ext cx="{int(w)}" cy="{int(h)}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
            f'<p:txBody><a:bodyPr wrap="square" anchor="{anchor}">'
            f'<a:normAutofit/></a:bodyPr><a:lstStyle/>{"".join(paras)}'
            f'</p:txBody></p:sp>')


# --------------------------------------------------------------------------- #
# per-layout composition
# --------------------------------------------------------------------------- #
def _decor_corner(t, sid):
    """A big soft accent circle bleeding off the top-right corner."""
    return _rect(sid, "decor", _W - 2200000, -1100000, 3300000, 3300000,
                 t["accent"], alpha=9000, geom="ellipse")


def _slide_shapes(slide: Slide, t: dict) -> tuple[str, str]:
    """Return (background_hex, inner spTree shapes) for a slide."""
    layout = slide.effective_layout()
    accent = _hex(slide.accent, t["accent"]) if slide.accent else t["accent"]
    bg = _hex(slide.bg, t["bg"]) if slide.bg else t["bg"]
    font_t, font_b = t["fonts"]["title"], t["fonts"]["body"]
    ink, muted = t["ink"], t["muted"]
    sid = iter(range(10, 400))
    sp = []

    if layout in ("cover", "section"):
        on_bg = bg
        if layout == "section":
            bg = accent
            ink_c = t["on_accent"]
            muted_c = t["on_accent"]
        else:
            ink_c = ink
            muted_c = muted
        # decorative band + corner
        sp.append(_rect(next(sid), "band", _MARGIN, _H * 0.60, 1500000, 26000,
                        accent if layout == "cover" else t["on_accent"]))
        if layout == "cover":
            sp.append(_decor_corner(t, next(sid)))
        title_runs = _run(slide.title or "", 46, ink_c, font_t, bold=True, spc=-20)
        sp.append(_textbox(next(sid), "title", _MARGIN, _H * 0.30,
                           _W - 2 * _MARGIN, 2200000,
                           [_para(title_runs, space_after=0)], anchor="b"))
        if slide.subtitle:
            sub_runs = _run(slide.subtitle, 20, muted_c, font_b)
            sp.append(_textbox(next(sid), "sub", _MARGIN, _H * 0.62,
                               _W - 2 * _MARGIN, 1100000,
                               [_para(sub_runs, space_after=0)]))
        return bg, "".join(sp)

    if layout == "statement":
        runs = _run(slide.title or slide.subtitle or "", 40, ink, font_t,
                    bold=True, spc=-20)
        sp.append(_rect(next(sid), "band", _MARGIN, _H * 0.40, 900000, 22000, accent))
        sp.append(_textbox(next(sid), "stmt", _MARGIN, _H * 0.44,
                           _W - 2 * _MARGIN, 2000000, [_para(runs, space_after=0)]))
        return bg, "".join(sp)

    if layout == "quote":
        mark = _run("“", 120, accent, font_t, bold=True)
        sp.append(_textbox(next(sid), "mark", _MARGIN - 40000, _H * 0.14,
                           1600000, 1600000, [_para(mark, space_after=0)]))
        q = _run(slide.quote or slide.title or "", 30, ink, font_t, italic=True)
        sp.append(_textbox(next(sid), "quote", _MARGIN, _H * 0.30,
                           _W - 2 * _MARGIN, 2600000, [_para(q, space_after=0)]))
        if slide.attribution:
            at = _run("— " + slide.attribution, 18, muted, font_b)
            sp.append(_textbox(next(sid), "attr", _MARGIN, _H * 0.70,
                               _W - 2 * _MARGIN, 700000, [_para(at, space_after=0)]))
        return bg, "".join(sp)

    # ---- content / two-column: title band at top, then body ----
    sp.append(_rect(next(sid), "dot", _MARGIN, 620000, 150000, 150000, accent,
                    geom="ellipse"))
    title_runs = _run(slide.title or "", 30, ink, font_t, bold=True, spc=-10)
    sp.append(_textbox(next(sid), "title", _MARGIN + 260000, 470000,
                       _W - 2 * _MARGIN - 260000, 900000,
                       [_para(title_runs, space_after=0)]))
    sp.append(_rect(next(sid), "rule", _MARGIN, 1420000, 1150000, 20000, accent))
    if slide.subtitle:
        sub = _run(slide.subtitle, 17, muted, font_b)
        sp.append(_textbox(next(sid), "sub", _MARGIN, 1520000,
                           _W - 2 * _MARGIN, 600000, [_para(sub, space_after=0)]))
    body_top = 2050000 if slide.subtitle else 1760000

    def bullet_paras(items):
        out = []
        for b in items:
            runs = _run(str(b), 18, ink, font_b)
            out.append(_para(runs, marL=320000, indent=-320000,
                             bu_color=accent, bu_char="•", space_after=1000))
        return out or [_para(_run("", 18, ink, font_b), space_after=0)]

    if layout == "two-column" and slide.columns:
        cols = slide.columns[:2]
        col_w = (_W - 2 * _MARGIN - 500000) / 2
        for ci, col in enumerate(cols):
            x = _MARGIN + ci * (col_w + 500000)
            sp.append(_textbox(next(sid), f"col{ci}", x, body_top, col_w,
                               _H - body_top - 500000, bullet_paras(col)))
    else:
        sp.append(_textbox(next(sid), "body", _MARGIN, body_top,
                           _W - 2 * _MARGIN, _H - body_top - 500000,
                           bullet_paras(slide.bullets)))
    return bg, "".join(sp)


def _slide_xml(slide: Slide, t: dict) -> str:
    bg, shapes = _slide_shapes(slide, t)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:cSld>'
        f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{bg}"/></a:solidFill>'
        '<a:effectLst/></p:bgPr></p:bg>'
        '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/>'
        '<p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/>'
        '<a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/>'
        '</a:xfrm></p:grpSpPr>'
        f'{shapes}'
        '</p:spTree></p:cSld>'
        '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


# --------------------------------------------------------------------------- #
# package scaffolding
# --------------------------------------------------------------------------- #
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
{slide_overrides}
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""


def _theme_xml(t: dict) -> str:
    c = t
    ft, fb = t["fonts"]["title"], t["fonts"]["body"]
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="ReverseAI">
<a:themeElements>
<a:clrScheme name="ReverseAI"><a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1><a:dk2><a:srgbClr val="{c['ink']}"/></a:dk2><a:lt2><a:srgbClr val="{c['surface']}"/></a:lt2><a:accent1><a:srgbClr val="{c['accent']}"/></a:accent1><a:accent2><a:srgbClr val="{c['accent2']}"/></a:accent2><a:accent3><a:srgbClr val="30D158"/></a:accent3><a:accent4><a:srgbClr val="FF9F0A"/></a:accent4><a:accent5><a:srgbClr val="FF375F"/></a:accent5><a:accent6><a:srgbClr val="64D2FF"/></a:accent6><a:hlink><a:srgbClr val="{c['accent']}"/></a:hlink><a:folHlink><a:srgbClr val="{c['accent2']}"/></a:folHlink></a:clrScheme>
<a:fontScheme name="ReverseAI"><a:majorFont><a:latin typeface="{_esc(ft)}"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont><a:minorFont><a:latin typeface="{_esc(fb)}"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>
<a:fmtScheme name="ReverseAI"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst><a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst><a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst><a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst></a:fmtScheme>
</a:themeElements></a:theme>"""


_SLIDE_MASTER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="lt1"/></p:bgRef></p:bg>
<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="4000" b="1"><a:solidFill><a:schemeClr val="dk2"/></a:solidFill><a:latin typeface="+mj-lt"/></a:defRPr></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr marL="342900" indent="-342900"><a:buChar char="&#8226;"/><a:defRPr sz="2000"><a:solidFill><a:schemeClr val="dk2"/></a:solidFill></a:defRPr></a:lvl1pPr></p:bodyStyle><p:otherStyle/></p:txStyles>
</p:sldMaster>"""

_SLIDE_MASTER_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""

_SLIDE_LAYOUT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" type="blank" preserve="1">
<p:cSld name="Blank"><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:spTree></p:cSld>
<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>"""

_SLIDE_LAYOUT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""

_SLIDE_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>"""


def _presentation_xml(n: int) -> str:
    sldids = "".join(
        f'<p:sldId id="{256 + i}" r:id="rId{i + 2}"/>' for i in range(n))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        f'<p:sldIdLst>{sldids}</p:sldIdLst>'
        f'<p:sldSz cx="{_W}" cy="{_H}" type="screen16x9"/>'
        f'<p:notesSz cx="{_H}" cy="{_W}"/></p:presentation>')


def _presentation_rels(n: int) -> str:
    rels = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/slideMaster" '
            'Target="slideMasters/slideMaster1.xml"/>']
    for i in range(n):
        rels.append(
            f'<Relationship Id="rId{i + 2}" Type="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/relationships/slide" '
            f'Target="slides/slide{i + 1}.xml"/>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(rels) + "</Relationships>")


def render_pptx(slides: list, theme=None) -> bytes:
    t = resolve_theme(theme)
    if not slides:
        slides = [Slide(title="Untitled")]
    overrides = "\n".join(
        f'<Override PartName="/ppt/slides/slide{i + 1}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(len(slides)))
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   _CONTENT_TYPES.format(slide_overrides=overrides))
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("ppt/presentation.xml", _presentation_xml(len(slides)))
        z.writestr("ppt/_rels/presentation.xml.rels",
                   _presentation_rels(len(slides)))
        z.writestr("ppt/theme/theme1.xml", _theme_xml(t))
        z.writestr("ppt/slideMasters/slideMaster1.xml", _SLIDE_MASTER)
        z.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels",
                   _SLIDE_MASTER_RELS)
        z.writestr("ppt/slideLayouts/slideLayout1.xml", _SLIDE_LAYOUT)
        z.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels",
                   _SLIDE_LAYOUT_RELS)
        for i, slide in enumerate(slides):
            z.writestr(f"ppt/slides/slide{i + 1}.xml", _slide_xml(slide, t))
            z.writestr(f"ppt/slides/_rels/slide{i + 1}.xml.rels", _SLIDE_RELS)
    return buf.getvalue()
