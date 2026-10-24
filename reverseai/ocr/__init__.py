"""Optical character recognition — read text from images, screenshots, PDFs.

Useful for mobile/app RE and design cloning: pull text out of app screenshots,
UI mockups, scanned docs, or images embedded in a binary. Uses the local
tesseract engine via pytesseract when available; a heavier model backend (e.g.
Baidu Unlimited-OCR) can be plugged in later. Degrades cleanly when no OCR
engine is installed.
"""

from .engine import ocr_available, ocr_image, ocr_pdf

__all__ = ["ocr_available", "ocr_image", "ocr_pdf"]
