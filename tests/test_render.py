"""Rasterizing generated files to page images (visual self-check)."""

import tempfile
import unittest
from pathlib import Path

from reverseai.docgen import generate
from reverseai.docgen.render import RenderError, render_file


class RenderTests(unittest.TestCase):
    def test_pdf_renders_pages(self):
        out = tempfile.mkdtemp()
        f = Path(out) / "doc.pdf"
        f.write_bytes(generate("pdf", {"title": "T", "blocks": [
            {"type": "paragraph", "text": "hello"}]}).data)
        pages = render_file(f, Path(out) / "r", max_pages=4)
        self.assertTrue(pages)
        self.assertTrue(all(p.endswith(".png") for p in pages))
        self.assertTrue(Path(pages[0]).stat().st_size > 100)

    def test_pptx_renders_pages(self):
        out = tempfile.mkdtemp()
        f = Path(out) / "deck.pptx"
        f.write_bytes(generate("pptx", {"slides": [
            {"title": "A"}, {"title": "B", "bullets": ["x"]}]}).data)
        pages = render_file(f, Path(out) / "r", dpi=80, max_pages=6)
        self.assertGreaterEqual(len(pages), 1)

    def test_unsupported_type_refused(self):
        out = tempfile.mkdtemp()
        f = Path(out) / "a.bin"
        f.write_bytes(b"\x00\x01")
        with self.assertRaises(RenderError):
            render_file(f, Path(out) / "r")

    def test_missing_file(self):
        with self.assertRaises(RenderError):
            render_file("/nope/missing.pdf", tempfile.mkdtemp())


if __name__ == "__main__":
    unittest.main()
