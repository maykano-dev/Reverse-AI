"""OCR engines — local Tesseract and Baidu Unlimited-OCR.

Two backends, one interface:

  * **Tesseract** via ``pytesseract`` (fast, local, no GPU).
  * **Unlimited-OCR** (Baidu) through an OpenAI-compatible vLLM/SGLang endpoint.
    Set ``REVERSEAI_OCR_URL`` (for example ``http://127.0.0.1:10000``) and the
    agent automatically prefers it for long documents and multi-page PDFs.
    ``REVERSEAI_OCR_MODEL`` defaults to ``Unlimited-OCR``.

Unlimited-OCR is not bundled: it needs a GPU and its own server. This adapter
talks to that server over HTTP, so ReverseAI stays dependency-light. The
Tesseract path remains the zero-setup fallback.
"""

from __future__ import annotations

import base64
import importlib.util
import io
import json
import mimetypes
import os
import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


def _have(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def ocr_available() -> bool:
    """True only if both pytesseract and the tesseract binary are present."""
    return _have("pytesseract") and _have("PIL") and shutil.which("tesseract") is not None


def unlimited_ocr_available() -> bool:
    return bool(os.environ.get("REVERSEAI_OCR_URL", "").strip())


def ocr_any_available() -> bool:
    return ocr_available() or unlimited_ocr_available()


@dataclass
class OcrResult:
    ok: bool
    text: str = ""
    pages: int = 1
    error: str | None = None
    engine: str = ""


# ---------------------------------------------------------------------------
# Tesseract
# ---------------------------------------------------------------------------

def ocr_image(path: str, lang: str = "eng") -> OcrResult:
    if not ocr_available():
        return OcrResult(False, error=(
            "no local OCR engine. Install tesseract (e.g. `sudo apt install "
            "tesseract-ocr`) and `pip install pytesseract pillow`, or set "
            "REVERSEAI_OCR_URL to an Unlimited-OCR server."))
    try:
        import pytesseract
        from PIL import Image

        text = pytesseract.image_to_string(Image.open(path), lang=lang)
        return OcrResult(True, text=text.strip(), engine="tesseract")
    except Exception as exc:
        return OcrResult(False, error=f"OCR failed: {exc}", engine="tesseract")


def ocr_pdf(path: str, lang: str = "eng", max_pages: int = 20) -> OcrResult:
    """OCR a PDF page by page. Needs PyMuPDF (fitz) to rasterise pages."""
    if not ocr_available():
        return OcrResult(False, error="no local OCR engine installed", engine="tesseract")
    if not _have("fitz"):
        return OcrResult(False, error="PDF OCR needs PyMuPDF (`pip install pymupdf`)",
                         engine="tesseract")
    try:
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
        return OcrResult(True, text="\n\n".join(chunks).strip(), pages=pages,
                         engine="tesseract")
    except Exception as exc:
        return OcrResult(False, error=f"PDF OCR failed: {exc}", engine="tesseract")


# ---------------------------------------------------------------------------
# Unlimited-OCR (OpenAI-compatible vLLM / SGLang)
# ---------------------------------------------------------------------------

def _endpoint() -> str:
    url = os.environ.get("REVERSEAI_OCR_URL", "").strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return url + "/chat/completions"
    return url + "/v1/chat/completions"


def _b64(path_or_bytes) -> tuple[str, str]:
    if isinstance(path_or_bytes, bytes):
        data, name = path_or_bytes, "image.png"
        mime = "image/png"
    else:
        p = Path(path_or_bytes)
        data = p.read_bytes()
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
    return base64.b64encode(data).decode("ascii"), mime


def _pdf_page_images(path: str, max_pages: int = 32, dpi: int = 220) -> list[bytes]:
    if not _have("fitz"):
        raise RuntimeError("PDF support needs PyMuPDF (`pip install pymupdf`)")
    import fitz

    doc = fitz.open(path)
    out: list[bytes] = []
    for i in range(min(len(doc), max_pages)):
        pix = doc[i].get_pixmap(dpi=dpi)
        out.append(pix.tobytes("png"))
    return out


def _parse_content(payload: dict) -> str:
    choice = (payload.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
            else:
                parts.append(str(part))
        return "\n".join(p for p in parts if p)
    # Some servers stream deltas even when stream=false; collect what we can.
    return str(choice.get("text") or "")


def ocr_unlimited(path: str, prompt: str = "document parsing.",
                  image_mode: str | None = None, timeout: float = 600.0) -> OcrResult:
    """Send an image or PDF to an Unlimited-OCR-compatible endpoint."""
    if not unlimited_ocr_available():
        return OcrResult(False, error="REVERSEAI_OCR_URL is not set", engine="unlimited-ocr")
    try:
        if str(path).lower().endswith(".pdf"):
            images = _pdf_page_images(path)
            pages = len(images)
            mode = image_mode or "base"
        else:
            images = [Path(path).read_bytes()]
            pages = 1
            mode = image_mode or "gundam"

        content: list[dict] = [{"type": "text", "text": prompt}]
        for raw in images:
            b64, mime = _b64(raw)
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"}})

        payload = {
            "model": os.environ.get("REVERSEAI_OCR_MODEL", "Unlimited-OCR"),
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "max_tokens": int(os.environ.get("REVERSEAI_OCR_MAX_TOKENS", "32768")),
            "stream": False,
            "images_config": {"image_mode": mode},
        }
        req = urllib.request.Request(
            _endpoint(),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
        text = _parse_content(body).strip()
        if not text:
            return OcrResult(False, error="Unlimited-OCR returned no text",
                             pages=pages, engine="unlimited-ocr")
        return OcrResult(True, text=text, pages=pages, engine="unlimited-ocr")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return OcrResult(False, error=f"Unlimited-OCR failed: {exc}",
                         engine="unlimited-ocr")


def ocr_best(path: str) -> OcrResult:
    """Use Unlimited-OCR when configured, then fall back to Tesseract."""
    if unlimited_ocr_available():
        res = ocr_unlimited(path)
        if res.ok:
            return res
        if not ocr_available():
            return res
    if str(path).lower().endswith(".pdf"):
        return ocr_pdf(path)
    return ocr_image(path)
