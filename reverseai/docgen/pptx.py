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
    image_data: bytes = b""          # embedded image bytes (png/jpeg)
    image_w: int = 0
    image_h: int = 0
    shapes: list = field(default_factory=list)   # diagram primitives (low-level)
    steps: list = field(default_factory=list)    # auto-laid-out flow/cycle labels
    diagram_style: str = "flow"      # flow | cycle | pillars
    animate: bool = False
    idx: int = 0                     # position in the deck (for varied decor)

    def effective_layout(self) -> str:
        if self.layout:
            return self.layout.lower()
        if self.shapes or self.steps:
            return "diagram"
        if self.quote:
            return "quote"
        if self.image_data and not self.bullets:
            return "image"
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


def _pic(sid, name, rid, x, y, cx, cy):
    return (f'<p:pic><p:nvPicPr><p:cNvPr id="{sid}" name="{name}"/>'
            f'<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/>'
            f'</p:nvPicPr><p:blipFill><a:blip r:embed="{rid}"/>'
            f'<a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f'<p:spPr><a:xfrm><a:off x="{int(x)}" y="{int(y)}"/>'
            f'<a:ext cx="{int(cx)}" cy="{int(cy)}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')


def _fit(iw, ih, bx, by, bw, bh):
    """Fit an image (px) inside a box (EMU), preserving aspect, centered."""
    if iw <= 0 or ih <= 0:
        return bx, by, bw, bh
    scale = min(bw / iw, bh / ih)
    cx, cy = iw * scale, ih * scale
    return bx + (bw - cx) / 2, by + (bh - cy) / 2, cx, cy


def _shade(hexv, factor):
    """Lighten (factor>0, toward white) or darken (factor<0) a hex color."""
    hexv = _hex(hexv, "2D6CDF")
    r, g, b = int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16)
    if factor >= 0:
        r, g, b = (int(c + (255 - c) * factor) for c in (r, g, b))
    else:
        f = 1 + factor
        r, g, b = (int(c * f) for c in (r, g, b))
    return f"{max(0, min(255, r)):02X}{max(0, min(255, g)):02X}{max(0, min(255, b)):02X}"


_SHADOW = ('<a:effectLst><a:outerShdw blurRad="90000" dist="30000" dir="5400000" '
           'rotWithShape="0"><a:srgbClr val="000000"><a:alpha val="20000"/>'
           '</a:srgbClr></a:outerShdw></a:effectLst>')


def _grad_fill(hexv):
    top, bot = _shade(hexv, 0.14), _shade(hexv, -0.12)
    return (f'<a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="{top}"/></a:gs>'
            f'<a:gs pos="100000"><a:srgbClr val="{bot}"/></a:gs></a:gsLst>'
            f'<a:lin ang="5400000" scaled="1"/></a:gradFill>')


def _flow_box(sid, x, y, w, h, fill, text, text_color, font):
    """A gradient-filled, soft-shadowed rounded card with centered, autosized text."""
    n = len(str(text))
    size = 18 if n <= 16 else 15 if n <= 34 else 12.5
    shape = (f'<p:sp><p:nvSpPr><p:cNvPr id="{next(sid)}" name="node"/><p:cNvSpPr/>'
             f'<p:nvPr/></p:nvSpPr><p:spPr><a:xfrm><a:off x="{int(x)}" y="{int(y)}"/>'
             f'<a:ext cx="{int(w)}" cy="{int(h)}"/></a:xfrm>'
             f'<a:prstGeom prst="roundRect"><a:avLst>'
             f'<a:gd name="adj" fmla="val 12000"/></a:avLst></a:prstGeom>'
             f'{_grad_fill(fill)}<a:ln><a:noFill/></a:ln>{_SHADOW}</p:spPr>'
             f'<p:txBody><a:bodyPr wrap="square" lIns="54000" rIns="54000" '
             f'tIns="20000" bIns="20000" anchor="ctr"><a:normAutofit/></a:bodyPr>'
             f'<a:lstStyle/>'
             + _para(_run(str(text), size, text_color, font, bold=True), algn="ctr",
                     space_after=0) + '</p:txBody></p:sp>')
    return shape


def _arrow_h(sid, x1, cy, x2, color):
    return (f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{next(sid)}" name="arrow"/>'
            f'<p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr><p:spPr>'
            f'<a:xfrm><a:off x="{int(x1)}" y="{int(cy)}"/>'
            f'<a:ext cx="{int(x2 - x1)}" cy="1"/></a:xfrm>'
            f'<a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
            f'<a:ln w="22225"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            f'<a:tailEnd type="triangle" w="med" len="med"/></a:ln></p:spPr></p:cxnSp>')


def _flow_diagram(steps, t, sid, area, style="flow"):
    """Auto-lay-out a clean flow/pillars diagram from step labels only.

    The engine owns sizing, spacing, alignment and color so the result is tidy
    regardless of what the model would have picked for raw coordinates.
    """
    left, top, w, h = area
    steps = [str(s) for s in steps if str(s).strip()][:6]
    if not steps:
        return ""
    n = len(steps)
    accent, accent2 = t["accent"], t["accent2"]
    on_acc = t["on_accent"]
    font_b = t["fonts"]["body"]
    colors = [accent, accent2]
    out = []

    # Tighter labels tend to be short; keep boxes proportional, not oversized.
    longest = max((len(s) for s in steps), default=8)
    two_line = longest > 18

    if style == "pillars" or (style == "flow" and n > 4):
        # Columns of equal cards, no arrows (good for 4+ parallel items).
        gap = int(w * 0.04)
        card_w = (w - (n - 1) * gap) / n
        card_h = min(h * 0.6, 2300000)
        cy = top + (h - card_h) / 2
        for i, s in enumerate(steps):
            x = left + i * (card_w + gap)
            out.append(_flow_box(sid, x, cy, card_w, card_h, colors[i % 2], s, on_acc, font_b))
        return "".join(out)

    # Horizontal flow with arrows between equal, proportionally sized boxes.
    arrow_gap = int(w * 0.075)
    box_w = (w - (n - 1) * arrow_gap) / n
    box_h = min(box_w * 0.62, 1250000 if two_line else 980000)
    by = top + (h - box_h) / 2
    cy = by + box_h / 2
    for i, s in enumerate(steps):
        x = left + i * (box_w + arrow_gap)
        out.append(_flow_box(sid, x, by, box_w, box_h, colors[i % 2], s, on_acc, font_b))
        if i < n - 1:
            ax1 = x + box_w + arrow_gap * 0.18
            ax2 = x + box_w + arrow_gap * 0.82
            out.append(_arrow_h(sid, ax1, cy, ax2, t["muted"]))
    return "".join(out)


def _diagram_shapes(shapes, t, sid, area):
    """Render simple diagram primitives into an area (left, top, w, h) EMU.

    Each shape: {type:'rect'|'ellipse'|'line'|'arrow'|'text', x,y,w,h (0..100),
    color?, text?, text_color?, size?, bold?}.
    """
    lft, top, aw, ah = area
    out = []

    def X(v): return lft + (float(v) / 100.0) * aw
    def Y(v): return top + (float(v) / 100.0) * ah
    def W(v): return (float(v) / 100.0) * aw
    def H(v): return (float(v) / 100.0) * ah

    for sh in shapes:
        if not isinstance(sh, dict):
            continue
        kind = str(sh.get("type") or "rect").lower()
        color = _hex(sh.get("color"), t["accent"])
        if kind in ("rect", "ellipse", "roundrect"):
            geom = "ellipse" if kind == "ellipse" else "roundRect" if kind == "roundrect" else "rect"
            rv = 8000 if kind == "roundrect" else None
            x, y, w, h = X(sh.get("x", 0)), Y(sh.get("y", 0)), W(sh.get("w", 20)), H(sh.get("h", 20))
            out.append(_rect(next(sid), "shape", x, y, w, h, color,
                             alpha=sh.get("alpha"), geom=geom, round_val=rv))
            if sh.get("text"):
                tc = _hex(sh.get("text_color"), t["on_accent"])
                runs = _run(sh["text"], float(sh.get("size") or 14), tc,
                            t["fonts"]["body"], bold=bool(sh.get("bold")))
                out.append(_textbox(next(sid), "lbl", x, y, w, h,
                                    [_para(runs, algn="ctr", space_after=0)], anchor="ctr"))
        elif kind in ("line", "arrow"):
            x1, y1 = X(sh.get("x", 0)), Y(sh.get("y", 0))
            x2, y2 = X(sh.get("x2", sh.get("x", 0))), Y(sh.get("y2", sh.get("y", 0)))
            ox, oy = min(x1, x2), min(y1, y2)
            ex, ey = abs(x2 - x1), abs(y2 - y1)
            flipH = ' flipH="1"' if x2 < x1 else ""
            flipV = ' flipV="1"' if y2 < y1 else ""
            weight = int(sh.get("weight") or 19050)
            tail = ('<a:tailEnd type="triangle" w="med" len="med"/>'
                    if kind == "arrow" else "")
            out.append(
                f'<p:cxnSp><p:nvCxnSpPr><p:cNvPr id="{next(sid)}" name="conn"/>'
                f'<p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr><p:spPr>'
                f'<a:xfrm{flipH}{flipV}><a:off x="{int(ox)}" y="{int(oy)}"/>'
                f'<a:ext cx="{int(ex) or 1}" cy="{int(ey) or 1}"/></a:xfrm>'
                f'<a:prstGeom prst="line"><a:avLst/></a:prstGeom>'
                f'<a:ln w="{weight}"><a:solidFill><a:srgbClr val="{color}"/>'
                f'</a:solidFill>{tail}</a:ln></p:spPr></p:cxnSp>')
        elif kind == "text":
            tc = _hex(sh.get("color"), t["ink"])
            runs = _run(sh.get("text", ""), float(sh.get("size") or 16), tc,
                        t["fonts"]["body"], bold=bool(sh.get("bold")))
            out.append(_textbox(next(sid), "txt", X(sh.get("x", 0)), Y(sh.get("y", 0)),
                                W(sh.get("w", 30)), H(sh.get("h", 10)),
                                [_para(runs, algn=sh.get("align", "l"), space_after=0)]))
    return "".join(out)


# --------------------------------------------------------------------------- #
# per-layout composition
# --------------------------------------------------------------------------- #
def _decor_corner(t, sid):
    """A big soft accent circle bleeding off the top-right corner."""
    return _rect(sid, "decor", _W - 2200000, -1100000, 3300000, 3300000,
                 t["accent"], alpha=9000, geom="ellipse")


def _auto_decor(t, idx, accent, sid):
    """A faint accent shape bleeding off a corner, varied per slide."""
    variants = [
        # (x, y, w, h, geom) - large soft shapes off a corner
        (_W - 2600000, _H - 2300000, 3600000, 3600000, "ellipse"),   # bottom-right circle
        (-1400000, _H - 2000000, 3200000, 3200000, "ellipse"),       # bottom-left circle
        (_W - 1700000, _H - 1500000, 2400000, 2400000, "ellipse"),   # smaller bottom-right
    ]
    x, y, w, h, geom = variants[idx % len(variants)]
    return _rect(sid, "decor", x, y, w, h, accent, alpha=6000, geom=geom)


def _img_ext(data: bytes) -> str:
    return "png" if data[:4] == b"\x89PNG" else "jpg"


def _slide_shapes(slide: Slide, t: dict):
    """Return (background_hex, shapes_xml, media, anim_ids).

    media: list of (local_rid, ext, bytes). anim_ids: shape ids to fade in.
    """
    layout = slide.effective_layout()
    accent = _hex(slide.accent, t["accent"]) if slide.accent else t["accent"]
    bg = _hex(slide.bg, t["bg"]) if slide.bg else t["bg"]
    font_t, font_b = t["fonts"]["title"], t["fonts"]["body"]
    ink, muted = t["ink"], t["muted"]
    sid = iter(range(10, 400))
    sp = []
    media = []
    anim = []

    def add_image(bx, by, bw, bh):
        if not slide.image_data:
            return
        rid = f"rId{100 + len(media)}"
        media.append((rid, _img_ext(bytes(slide.image_data)), bytes(slide.image_data)))
        x, y, cx, cy = _fit(slide.image_w, slide.image_h, bx, by, bw, bh)
        iid = next(sid)
        sp.append(_pic(iid, "image", rid, x, y, cx, cy))
        if slide.animate:
            anim.append(iid)

    if layout in ("cover", "section"):
        if layout == "section":
            bg = accent
            ink_c = muted_c = t["on_accent"]
        else:
            ink_c, muted_c = ink, muted
        sp.append(_rect(next(sid), "band", _MARGIN, _H * 0.60, 1500000, 26000,
                        accent if layout == "cover" else t["on_accent"]))
        if layout == "cover":
            sp.append(_decor_corner(t, next(sid)))
        tid = next(sid)
        sp.append(_textbox(tid, "title", _MARGIN, _H * 0.30, _W - 2 * _MARGIN, 2200000,
                           [_para(_run(slide.title or "", 46, ink_c, font_t, bold=True,
                                       spc=-20), space_after=0)], anchor="b"))
        if slide.subtitle:
            sp.append(_textbox(next(sid), "sub", _MARGIN, _H * 0.62, _W - 2 * _MARGIN,
                               1100000, [_para(_run(slide.subtitle, 20, muted_c, font_b),
                                                space_after=0)]))
        if slide.animate:
            anim.append(tid)
        return bg, "".join(sp), media, anim

    if layout == "statement":
        sp.append(_rect(next(sid), "band", _MARGIN, _H * 0.40, 900000, 22000, accent))
        sp.append(_textbox(next(sid), "stmt", _MARGIN, _H * 0.44, _W - 2 * _MARGIN,
                           2000000, [_para(_run(slide.title or slide.subtitle or "", 40,
                                                ink, font_t, bold=True, spc=-20),
                                            space_after=0)]))
        return bg, "".join(sp), media, anim

    if layout == "quote":
        sp.append(_textbox(next(sid), "mark", _MARGIN - 40000, _H * 0.14, 1600000,
                           1600000, [_para(_run("“", 120, accent, font_t, bold=True),
                                           space_after=0)]))
        sp.append(_textbox(next(sid), "quote", _MARGIN, _H * 0.30, _W - 2 * _MARGIN,
                           2600000, [_para(_run(slide.quote or slide.title or "", 30,
                                                ink, font_t, italic=True), space_after=0)]))
        if slide.attribution:
            sp.append(_textbox(next(sid), "attr", _MARGIN, _H * 0.70, _W - 2 * _MARGIN,
                               700000, [_para(_run("— " + slide.attribution, 18,
                                                   muted, font_b), space_after=0)]))
        return bg, "".join(sp), media, anim

    # ---- title header shared by content / two-column / image / diagram ----
    # Subtle, cohesive decoration so slides aren't flat text: a faint accent
    # shape bleeding off a corner, alternating per slide for variety.
    if layout in ("content", "two-column"):
        sp.append(_auto_decor(t, slide.idx, accent, next(sid)))
    sp.append(_rect(next(sid), "dot", _MARGIN, 620000, 150000, 150000, accent,
                    geom="ellipse"))
    sp.append(_textbox(next(sid), "title", _MARGIN + 260000, 470000,
                       _W - 2 * _MARGIN - 260000, 900000,
                       [_para(_run(slide.title or "", 30, ink, font_t, bold=True, spc=-10),
                              space_after=0)]))
    sp.append(_rect(next(sid), "rule", _MARGIN, 1420000, 1150000, 20000, accent))
    if slide.subtitle:
        sp.append(_textbox(next(sid), "sub", _MARGIN, 1520000, _W - 2 * _MARGIN, 600000,
                           [_para(_run(slide.subtitle, 17, muted, font_b), space_after=0)]))
    body_top = 2050000 if slide.subtitle else 1760000
    body_h = _H - body_top - 500000

    if layout == "diagram":
        area = (_MARGIN, body_top, _W - 2 * _MARGIN, body_h)
        if slide.steps:
            sp.append(_flow_diagram(slide.steps, t, sid, area, slide.diagram_style))
        else:
            sp.append(_diagram_shapes(slide.shapes, t, sid, area))
        return bg, "".join(sp), media, anim

    def bullet_paras(items):
        out = [_para(_run(str(b), 18, ink, font_b), marL=320000, indent=-320000,
                     bu_color=accent, bu_char="•", space_after=1000) for b in items]
        return out or [_para(_run("", 18, ink, font_b), space_after=0)]

    if layout == "image":
        add_image(_MARGIN, body_top, _W - 2 * _MARGIN, body_h)
        return bg, "".join(sp), media, anim

    if slide.image_data:
        # text left, image right
        text_w = (_W - 2 * _MARGIN) * 0.52
        bid = next(sid)
        sp.append(_textbox(bid, "body", _MARGIN, body_top, text_w, body_h,
                           bullet_paras(slide.bullets)))
        if slide.animate:
            anim.append(bid)
        img_x = _MARGIN + text_w + 400000
        add_image(img_x, body_top, _W - _MARGIN - img_x, body_h)
    elif layout == "two-column" and slide.columns:
        cols = slide.columns[:2]
        col_w = (_W - 2 * _MARGIN - 500000) / 2
        for ci, col in enumerate(cols):
            x = _MARGIN + ci * (col_w + 500000)
            cid = next(sid)
            sp.append(_textbox(cid, f"col{ci}", x, body_top, col_w, body_h,
                               bullet_paras(col)))
            if slide.animate:
                anim.append(cid)
    else:
        bid = next(sid)
        sp.append(_textbox(bid, "body", _MARGIN, body_top, _W - 2 * _MARGIN, body_h,
                           bullet_paras(slide.bullets)))
        if slide.animate:
            anim.append(bid)
    return bg, "".join(sp), media, anim


def _timing_fade(anim_ids: list) -> str:
    """A conservative sequential fade-in entrance for the given shape ids.

    Experimental: OOXML timing is strict. Kept simple (one fade per shape, on
    the main sequence) so the file still opens if a viewer ignores animations.
    """
    if not anim_ids:
        return ""
    effects = []
    cid = 10
    for spid in anim_ids:
        effects.append(
            f'<p:par><p:cTn id="{cid}" fill="hold"><p:stCondLst>'
            f'<p:cond delay="{"0" if cid == 10 else "indefinite"}"/></p:stCondLst>'
            f'<p:childTnLst><p:par><p:cTn id="{cid + 1}" fill="hold"><p:stCondLst>'
            f'<p:cond delay="0"/></p:stCondLst><p:childTnLst><p:par>'
            f'<p:cTn id="{cid + 2}" presetID="10" presetClass="entr" presetSubtype="0" '
            f'fill="hold" nodeType="{"clickEffect" if cid == 10 else "afterEffect"}">'
            f'<p:stCondLst><p:cond delay="0"/></p:stCondLst><p:childTnLst>'
            f'<p:set><p:cBhvr><p:cTn id="{cid + 3}" dur="1" fill="hold"><p:stCondLst>'
            f'<p:cond delay="0"/></p:stCondLst></p:cTn><p:tgtEl><p:spTgt spid="{spid}"/>'
            f'</p:tgtEl><p:attrNameLst><p:attrName>style.visibility</p:attrName>'
            f'</p:attrNameLst></p:cBhvr><p:to><p:strVal val="visible"/></p:to></p:set>'
            f'<p:animEffect transition="in" filter="fade"><p:cBhvr>'
            f'<p:cTn id="{cid + 4}" dur="500"/><p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'
            f'</p:cBhvr></p:animEffect></p:childTnLst></p:cTn></p:par></p:childTnLst>'
            f'</p:cTn></p:par></p:childTnLst></p:cTn></p:par>')
        cid += 10
    return (
        '<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" '
        'nodeType="tmRoot"><p:childTnLst><p:seq concurrent="1" nextAc="seek">'
        '<p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
        + "".join(effects) +
        '</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0">'
        '<p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
        '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl>'
        '</p:cond></p:nextCondLst></p:seq></p:childTnLst></p:cTn></p:par></p:tnLst></p:timing>')


def _bg_fill(bg: str) -> str:
    """A subtle vertical gradient for depth (bg -> slightly darker at the base)."""
    return (f'<a:gradFill><a:gsLst><a:gs pos="0"><a:srgbClr val="{bg}"/></a:gs>'
            f'<a:gs pos="100000"><a:srgbClr val="{_shade(bg, -0.05)}"/></a:gs></a:gsLst>'
            f'<a:lin ang="5400000" scaled="1"/></a:gradFill>')


def _slide_xml(slide: Slide, t: dict):
    bg, shapes, media, anim = _slide_shapes(slide, t)
    timing = _timing_fade(anim) if slide.animate else ""
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:cSld>'
        f'<p:bg><p:bgPr>{_bg_fill(bg)}<a:effectLst/></p:bgPr></p:bg>'
        '<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/>'
        '<p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm><a:off x="0" y="0"/>'
        '<a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/>'
        '</a:xfrm></p:grpSpPr>'
        f'{shapes}'
        '</p:spTree></p:cSld>'
        '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>'
        f'{timing}</p:sld>')
    return xml, media


def _slide_rels(media) -> str:
    rels = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
            'officeDocument/2006/relationships/slideLayout" '
            'Target="../slideLayouts/slideLayout1.xml"/>']
    for gi, (rid, ext, _data) in media:
        rels.append(
            f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/relationships/image" Target="../media/image{gi}.{ext}"/>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + "".join(rels) + "</Relationships>")


# --------------------------------------------------------------------------- #
# package scaffolding
# --------------------------------------------------------------------------- #
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="jpg" ContentType="image/jpeg"/>
<Default Extension="jpeg" ContentType="image/jpeg"/>
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
        media_n = 0
        for i, slide in enumerate(slides):
            slide.idx = i
            xml, media = _slide_xml(slide, t)
            z.writestr(f"ppt/slides/slide{i + 1}.xml", xml)
            indexed = []
            for (rid, ext, data) in media:
                media_n += 1
                z.writestr(f"ppt/media/image{media_n}.{ext}", data)
                indexed.append((media_n, (rid, ext, data)))
            z.writestr(f"ppt/slides/_rels/slide{i + 1}.xml.rels",
                       _slide_rels(indexed))
    return buf.getvalue()
