"""Rasterize SVG to PNG so the model's own vector art can be embedded.

The model is good at writing SVG (circuit schematics, waveforms, charts,
illustrations). PowerPoint/Word/PDF across all viewers render an embedded PNG
far more reliably than inline SVG, so we rasterize here. LibreOffice has
excellent SVG support; ImageMagick is a fallback. No required Python packages.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def available() -> bool:
    return bool(shutil.which("soffice") or shutil.which("libreoffice")
                or shutil.which("convert"))


def _scale_svg(svg: str, target_w: int) -> str:
    """Nudge the SVG's width/height up to target_w (keeps aspect via viewBox)."""
    m = re.search(r'<svg\b[^>]*>', svg, re.IGNORECASE)
    if not m:
        return svg
    tag = m.group(0)
    vb = re.search(r'viewBox="([\d.\s-]+)"', tag)
    wv = re.search(r'\bwidth="([\d.]+)', tag)
    hv = re.search(r'\bheight="([\d.]+)', tag)
    try:
        if vb:
            parts = [float(x) for x in vb.group(1).split()]
            vw, vh = parts[2], parts[3]
        elif wv and hv:
            vw, vh = float(wv.group(1)), float(hv.group(1))
        else:
            return svg
        if vw <= 0:
            return svg
        scale = max(1.0, target_w / vw)
        nw, nh = int(vw * scale), int(vh * scale)
    except (ValueError, IndexError):
        return svg
    new = tag
    new = re.sub(r'\bwidth="[^"]*"', f'width="{nw}"', new) if wv else \
        new[:-1] + f' width="{nw}">'
    new = re.sub(r'\bheight="[^"]*"', f'height="{nh}"', new) if hv else \
        new[:-1] + f' height="{nh}">'
    return svg.replace(tag, new, 1)


def svg_to_png(svg, target_w: int = 1400) -> bytes | None:
    """Return PNG bytes for an SVG string/bytes, or None if no rasterizer works."""
    if isinstance(svg, bytes):
        svg = svg.decode("utf-8", "replace")
    svg = _scale_svg(svg.strip(), target_w)
    data = svg.encode("utf-8")
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "art.svg"
            src.write_bytes(data)
            try:
                subprocess.run(
                    [soffice, "--headless", "--norestore", "--convert-to", "png",
                     "--outdir", td, str(src)],
                    capture_output=True, timeout=90, check=False)
                out = Path(td) / "art.png"
                if out.is_file() and out.stat().st_size > 64:
                    return out.read_bytes()
            except (subprocess.TimeoutExpired, OSError):
                pass
    convert = shutil.which("convert")
    if convert:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "art.svg"
            src.write_bytes(data)
            out = Path(td) / "art.png"
            try:
                subprocess.run(
                    [convert, "-background", "none", "-density", "150",
                     str(src), str(out)],
                    capture_output=True, timeout=60, check=False)
                if out.is_file() and out.stat().st_size > 64:
                    return out.read_bytes()
            except (subprocess.TimeoutExpired, OSError):
                pass
    return None
