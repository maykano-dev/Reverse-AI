"""Rasterize a generated document to page images, so it can be *seen*.

PDFs go straight through pdftoppm (poppler). Office files (pptx/docx/xlsx) are
converted to PDF with headless LibreOffice first. This lets the agent look at
its own output and fix layout before delivering, and lets the user view a
render in the chat. No third-party Python packages; uses the system tools that
are already relied on for validation.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

_OFFICE = {".pptx", ".docx", ".xlsx", ".odp", ".odt", ".ods", ".ppt", ".doc", ".xls"}


class RenderError(Exception):
    pass


def _which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def render_file(path, out_dir, dpi: int = 120, max_pages: int = 8) -> list[str]:
    """Render ``path`` to PNG page images in ``out_dir``; return their paths."""
    src = Path(path)
    if not src.is_file():
        raise RenderError("file not found")
    ext = src.suffix.lower()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    max_pages = max(1, min(int(max_pages or 8), 40))

    pdf = src
    tmp = None
    if ext == ".pdf":
        pass
    elif ext in _OFFICE:
        soffice = _which("soffice", "libreoffice")
        if not soffice:
            raise RenderError("LibreOffice (soffice) is not installed on this host")
        tmp = tempfile.TemporaryDirectory()
        try:
            subprocess.run(
                [soffice, "--headless", "--norestore", "--nolockcheck",
                 "--convert-to", "pdf", "--outdir", tmp.name, str(src)],
                capture_output=True, timeout=180, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            tmp.cleanup()
            raise RenderError(f"conversion to PDF failed: {exc}") from exc
        made = sorted(Path(tmp.name).glob("*.pdf"))
        if not made:
            tmp.cleanup()
            raise RenderError("LibreOffice did not produce a PDF to render")
        pdf = made[0]
    else:
        raise RenderError(f"cannot render {ext or 'this file'} "
                          "(supported: pdf, pptx, docx, xlsx)")

    pdftoppm = _which("pdftoppm")
    if not pdftoppm:
        if tmp:
            tmp.cleanup()
        raise RenderError("pdftoppm (poppler-utils) is not installed on this host")

    prefix = out / src.stem
    try:
        subprocess.run(
            [pdftoppm, "-png", "-r", str(int(dpi)), "-l", str(max_pages),
             str(pdf), str(prefix)],
            capture_output=True, timeout=180, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        if tmp:
            tmp.cleanup()
        raise RenderError(f"rendering failed: {exc}") from exc
    finally:
        if tmp:
            tmp.cleanup()

    pages = sorted(out.glob(src.stem + "-*.png"))
    if not pages:
        single = out / (src.stem + ".png")
        if single.exists():
            pages = [single]
    if not pages:
        raise RenderError("no pages were rendered")
    return [str(p) for p in pages[:max_pages]]
