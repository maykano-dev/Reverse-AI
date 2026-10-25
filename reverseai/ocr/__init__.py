"""Optical character recognition — read text from images, screenshots, PDFs.

Useful for mobile/app RE and design cloning: pull text out of app screenshots,
UI mockups, scanned docs, or images embedded in a binary.

Two backends:
  * local Tesseract (zero setup beyond the system package)
  * Baidu Unlimited-OCR via an OpenAI-compatible vLLM/SGLang endpoint
    (set ``REVERSEAI_OCR_URL``)

The agent picks the best configured engine automatically.
"""

from .engine import (
    OcrResult,
    ocr_any_available,
    ocr_available,
    ocr_best,
    ocr_image,
    ocr_pdf,
    ocr_unlimited,
    unlimited_ocr_available,
)

__all__ = [
    "ocr_available",
    "ocr_any_available",
    "unlimited_ocr_available",
    "ocr_image",
    "ocr_pdf",
    "ocr_unlimited",
    "ocr_best",
    "OcrResult",
]
