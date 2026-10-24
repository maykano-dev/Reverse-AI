"""OCR engine wrapper (tesseract via pytesseract), optional."""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import dataclass


def _have(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def ocr_available() -> bool:
    """True only if both pytesseract and the tesseract binary are present."""
    return _have("pytesseract") and _have("PIL") and shutil.which("tesseract") is not None


@dataclass
class OcrResult:
    ok: bool
    text: str = ""
    pages: int = 1
    error: str | None = None


def ocr_image(path: str, lang: str = "eng") -> OcrResult:
    if not ocr_available():
        return OcrResult(False, error=(
            "no OCR engine. Install tesseract (e.g. `sudo apt install "
            "tesseract-ocr`) and `pip install pytesseract pillow`."))
    try:
        import pytesseract
        from PIL import Image

        text = pytesseract.image_to_string(Image.open(path), lang=lang)
        return OcrResult(True, text=text.strip())
    except Exception as exc:
        return OcrResult(False, error=f"OCR failed: {exc}")


def ocr_pdf(path: str, lang: str = "eng", max_pages: int = 20) -> OcrResult:
    """OCR a PDF page by page. Needs PyMuPDF (fitz) to rasterise pages."""
    if not ocr_available():
        return OcrResult(False, error="no OCR engine installed")
    if not _have("fitz"):
        return OcrResult(False, error="PDF OCR needs PyMuPDF (`pip install pymupdf`)")
    try:
        import io

        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image

        doc = fitz.open(path)
        chunks = []
        pages = min(len(doc), max_pages)
        for i in range(pages):
            pix = doc[i].get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            chunks.append(f"--- page {i + 1} ---\n" + pytesseract.image_to_string(img, lang=lang))
        return OcrResult(True, text="\n\n".join(chunks).strip(), pages=pages)
    except Exception as exc:
        return OcrResult(False, error=f"PDF OCR failed: {exc}")
