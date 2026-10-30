"""Data-driven charts as themed SVG - the model gives numbers, we draw.

Reliable, vetted vector art (bar, line, area, donut) so a deck/doc/page gets a
real chart without the model hand-drawing SVG. The SVG is rasterized and
embedded by the normal image pipeline. Pure Python, no plotting libraries.
"""

from __future__ import annotations

import html
import math

_W, _H = 1000, 600


def _hx(c, fallback):
    s = str(c or "").lstrip("#").upper()
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    return "#" + s if len(s) == 6 and all(ch in "0123456789ABCDEF" for ch in s) else "#" + fallback


def _e(s):
    return html.escape(str(s), quote=True)


def _palette(colors):
    c = colors or {}
    return {
        "bg": _hx(c.get("bg"), "FFFFFF"),
        "ink": _hx(c.get("ink"), "16181D"),
        "muted": _hx(c.get("muted"), "5C6672"),
        "accent": _hx(c.get("accent"), "2D6CDF"),
        "accent2": _hx(c.get("accent2"), "7C5CFF"),
        "grid": _hx(c.get("muted"), "5C6672"),
        "font": str(c.get("font") or "Helvetica Neue, Arial, sans-serif"),
        "series": [_hx(c.get("accent"), "2D6CDF"), _hx(c.get("accent2"), "7C5CFF"),
                   "#2AD6B5", "#FF9F0A", "#FF6B6B", "#64D2FF"],
    }


def _pairs(data):
    out = []
    for d in data or []:
        if isinstance(d, dict):
            out.append((str(d.get("label", "")), float(d.get("value", 0) or 0)))
        elif isinstance(d, (list, tuple)) and len(d) >= 2:
            out.append((str(d[0]), float(d[1] or 0)))
        else:
            out.append(("", float(d or 0)))
    return out


def _nice_max(v):
    if v <= 0:
        return 1.0
    mag = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * mag:
            return m * mag
    return 10 * mag


def _bar(data, p, title):
    pts = _pairs(data)[:8]
    if not pts:
        return ""
    ml, mr, mt, mb = 70, 30, (90 if title else 40), 80
    cw, ch = _W - ml - mr, _H - mt - mb
    vmax = _nice_max(max((v for _, v in pts), default=1))
    n = len(pts)
    slot = cw / n
    bw = slot * 0.56
    out = []
    # gridlines + y labels
    for i in range(5):
        gy = mt + ch * i / 4
        val = vmax * (1 - i / 4)
        out.append(f'<line x1="{ml}" y1="{gy:.0f}" x2="{ml + cw}" y2="{gy:.0f}" '
                   f'stroke="{p["grid"]}" stroke-opacity="0.15" stroke-width="1"/>')
        out.append(f'<text x="{ml - 12}" y="{gy + 5:.0f}" fill="{p["muted"]}" '
                   f'font-size="20" text-anchor="end" font-family="{p["font"]}">'
                   f'{val:g}</text>')
    for i, (label, v) in enumerate(pts):
        bh = ch * (v / vmax) if vmax else 0
        x = ml + i * slot + (slot - bw) / 2
        y = mt + ch - bh
        out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{bw:.0f}" height="{bh:.0f}" '
                   f'rx="6" fill="{p["accent"]}"/>')
        out.append(f'<text x="{x + bw / 2:.0f}" y="{y - 12:.0f}" fill="{p["ink"]}" '
                   f'font-size="20" font-weight="bold" text-anchor="middle" '
                   f'font-family="{p["font"]}">{v:g}</text>')
        out.append(f'<text x="{x + bw / 2:.0f}" y="{mt + ch + 34:.0f}" fill="{p["muted"]}" '
                   f'font-size="20" text-anchor="middle" font-family="{p["font"]}">'
                   f'{_e(label)}</text>')
    return "".join(out)


def _line(series, p, title, area=False):
    # series: [{name, data:[{label,value}|value]}] or a single data list
    if series and isinstance(series[0], dict) and "data" in series[0]:
        groups = series
    else:
        groups = [{"name": "", "data": series}]
    allpts = [_pairs(g.get("data")) for g in groups]
    labels = [l for l, _ in allpts[0]] if allpts and allpts[0] else []
    vmax = _nice_max(max((v for pts in allpts for _, v in pts), default=1))
    ml, mr, mt, mb = 70, 40, (90 if title else 40), 80
    cw, ch = _W - ml - mr, _H - mt - mb
    out = []
    for i in range(5):
        gy = mt + ch * i / 4
        out.append(f'<line x1="{ml}" y1="{gy:.0f}" x2="{ml + cw}" y2="{gy:.0f}" '
                   f'stroke="{p["grid"]}" stroke-opacity="0.15" stroke-width="1"/>')
        out.append(f'<text x="{ml - 12}" y="{gy + 5:.0f}" fill="{p["muted"]}" '
                   f'font-size="20" text-anchor="end" font-family="{p["font"]}">'
                   f'{vmax * (1 - i / 4):g}</text>')
    for gi, pts in enumerate(allpts):
        n = len(pts)
        if n == 0:
            continue
        col = p["series"][gi % len(p["series"])]
        coords = [(ml + (cw * (j / (n - 1)) if n > 1 else cw / 2),
                   mt + ch - ch * (v / vmax if vmax else 0)) for j, (_, v) in enumerate(pts)]
        d = "M" + " L".join(f"{x:.0f},{y:.0f}" for x, y in coords)
        if area:
            ad = d + f" L{coords[-1][0]:.0f},{mt + ch} L{coords[0][0]:.0f},{mt + ch} Z"
            out.append(f'<path d="{ad}" fill="{col}" fill-opacity="0.14"/>')
        out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="4" '
                   f'stroke-linejoin="round" stroke-linecap="round"/>')
        for x, y in coords:
            out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="6" fill="{col}"/>')
    for j, label in enumerate(labels):
        n = len(labels)
        x = ml + (cw * (j / (n - 1)) if n > 1 else cw / 2)
        out.append(f'<text x="{x:.0f}" y="{mt + ch + 34:.0f}" fill="{p["muted"]}" '
                   f'font-size="20" text-anchor="middle" font-family="{p["font"]}">'
                   f'{_e(label)}</text>')
    return "".join(out)


def _donut(data, p, title):
    pts = _pairs(data)[:6]
    total = sum(v for _, v in pts) or 1
    cx, cy, R, r = 340, (330 if title else 300), 190, 110
    out, ang = [], -math.pi / 2
    for i, (label, v) in enumerate(pts):
        frac = v / total
        a2 = ang + frac * 2 * math.pi
        large = 1 if frac > 0.5 else 0
        x1, y1 = cx + R * math.cos(ang), cy + R * math.sin(ang)
        x2, y2 = cx + R * math.cos(a2), cy + R * math.sin(a2)
        xi1, yi1 = cx + r * math.cos(a2), cy + r * math.sin(a2)
        xi2, yi2 = cx + r * math.cos(ang), cy + r * math.sin(ang)
        col = p["series"][i % len(p["series"])]
        out.append(f'<path d="M{x1:.1f},{y1:.1f} A{R},{R} 0 {large} 1 {x2:.1f},{y2:.1f} '
                   f'L{xi1:.1f},{yi1:.1f} A{r},{r} 0 {large} 0 {xi2:.1f},{yi2:.1f} Z" '
                   f'fill="{col}"/>')
        ang = a2
    # legend
    lx, ly = 620, (cy - len(pts) * 25)
    for i, (label, v) in enumerate(pts):
        col = p["series"][i % len(p["series"])]
        y = ly + i * 50
        out.append(f'<rect x="{lx}" y="{y}" width="26" height="26" rx="5" fill="{col}"/>')
        out.append(f'<text x="{lx + 40}" y="{y + 21}" fill="{p["ink"]}" font-size="22" '
                   f'font-family="{p["font"]}">{_e(label)} '
                   f'<tspan fill="{p["muted"]}">{v / total * 100:.0f}%</tspan></text>')
    return "".join(out)


def render_chart(spec, colors=None) -> str:
    """Return a themed SVG string for a chart spec, or '' if nothing to draw."""
    if not isinstance(spec, dict):
        return ""
    p = _palette(colors)
    kind = str(spec.get("type") or spec.get("kind") or "bar").lower()
    title = str(spec.get("title") or "")
    data = spec.get("data") or spec.get("series") or []
    if kind in ("line",):
        body = _line(data, p, title)
    elif kind in ("area",):
        body = _line(data, p, title, area=True)
    elif kind in ("donut", "doughnut", "pie"):
        body = _donut(data, p, title)
    else:
        body = _bar(data, p, title)
    if not body:
        return ""
    head = (f'<text x="40" y="52" fill="{p["ink"]}" font-size="30" font-weight="bold" '
            f'font-family="{p["font"]}">{_e(title)}</text>' if title else "")
    bg = (f'<rect width="{_W}" height="{_H}" fill="{p["bg"]}"/>'
          if spec.get("background") else "")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_W} {_H}">'
            f'{bg}{head}{body}</svg>')
