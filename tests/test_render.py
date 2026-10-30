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


class SvgRasterTests(unittest.TestCase):
    def test_svg_to_png(self):
        from reverseai.docgen.svgraster import available, svg_to_png
        if not available():
            self.skipTest("no SVG rasterizer on host")
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120">'
               '<circle cx="60" cy="60" r="40" fill="#2D6CDF"/>'
               '<text x="10" y="20" font-size="14">Hi</text></svg>')
        png = svg_to_png(svg, target_w=800)
        self.assertTrue(png and png[:4] == b"\x89PNG")

    def test_svg_embeds_in_deck(self):
        from reverseai.docgen import generate
        from reverseai.docgen.svgraster import available
        from reverseai.studio import embed_images
        if not available():
            self.skipTest("no SVG rasterizer on host")
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 180">'
               '<rect width="300" height="180" fill="#101010"/>'
               '<circle cx="90" cy="90" r="50" fill="#FF9F0A"/></svg>')
        spec = {"slides": [{"title": "Art", "svg": svg, "bullets": ["x"]}]}
        embed_images(spec, tempfile.mkdtemp())
        self.assertIsInstance(spec["slides"][0].get("image_data"), (bytes, bytearray))
        import zipfile
        from io import BytesIO
        z = zipfile.ZipFile(BytesIO(generate("pptx", spec).data))
        self.assertTrue(any("media/image" in n for n in z.namelist()))
