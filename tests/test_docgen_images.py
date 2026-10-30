"""Image decoding and embedding into generated PDFs (zero dependencies)."""

import struct
import tempfile
import unittest
import zipfile
import zlib
from io import BytesIO
from pathlib import Path

from reverseai.docgen import generate
from reverseai.docgen.images import ImageError, decode_image


def _png(w, h):
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter: none
        for x in range(w):
            raw += bytes([(x * 255) // max(1, w - 1), (y * 255) // max(1, h - 1), 128])

    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw)))
            + chunk(b"IEND", b""))


class ImageDecodeTests(unittest.TestCase):
    def test_png_rgb_decodes_to_raw(self):
        d = decode_image(_png(10, 6))
        self.assertEqual((d.width, d.height, d.fmt), (10, 6, "rgb"))
        self.assertEqual(len(d.data), 10 * 6 * 3)

    def test_png_rgba_flattens(self):
        # 2x1 RGBA, one opaque red, one transparent
        raw = bytes([0]) + bytes([255, 0, 0, 255, 0, 0, 255, 0])

        def chunk(typ, data):
            c = typ + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)

        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw))
               + chunk(b"IEND", b""))
        d = decode_image(png)
        self.assertEqual(d.fmt, "rgb")
        self.assertEqual(d.data[:3], bytes([255, 0, 0]))        # opaque red kept
        self.assertEqual(d.data[3:6], bytes([255, 255, 255]))   # transparent -> white

    def test_unknown_format_refused(self):
        with self.assertRaises(ImageError):
            decode_image(b"GIF89a" + b"\x00" * 40)


class PdfImageEmbedTests(unittest.TestCase):
    def test_embedded_image_produces_xobject(self):
        ws = tempfile.mkdtemp()
        (Path(ws) / "assets").mkdir()
        (Path(ws) / "assets" / "g.png").write_bytes(_png(40, 30))
        from reverseai.studio import embed_images
        spec = {"title": "Img", "blocks": [
            {"type": "image", "src": "assets/g.png", "caption": "cap"}]}
        embed_images(spec, ws)
        self.assertIsInstance(spec["blocks"][0].get("data"), (bytes, bytearray))
        data = generate("pdf", spec, name="img").data
        self.assertTrue(data.startswith(b"%PDF-"))
        self.assertIn(b"/Subtype /Image", data)
        self.assertIn(b"/DeviceRGB", data)

    def test_missing_image_is_skipped_not_fatal(self):
        ws = tempfile.mkdtemp()
        from reverseai.studio import embed_images
        spec = {"title": "Img", "blocks": [{"type": "image", "src": "nope.png"}]}
        embed_images(spec, ws)
        data = generate("pdf", spec, name="img").data
        self.assertTrue(data.startswith(b"%PDF-"))  # renders without the image


if __name__ == "__main__":
    unittest.main()


def _png_bytes(w, h):
    return _png(w, h)


class DocxImageTests(unittest.TestCase):
    def test_docx_embeds_image(self):
        import tempfile
        from pathlib import Path
        from reverseai.studio import embed_images
        ws = tempfile.mkdtemp()
        (Path(ws) / "assets").mkdir()
        (Path(ws) / "assets" / "p.png").write_bytes(_png(60, 40))
        spec = {"title": "Doc", "blocks": [
            {"type": "image", "src": "assets/p.png", "caption": "fig"}]}
        embed_images(spec, ws)
        data = generate("docx", spec, name="d").data
        z = zipfile.ZipFile(BytesIO(data))
        self.assertIsNone(z.testzip())
        self.assertIn("word/media/image1.png", z.namelist())
        self.assertIn(b"<w:drawing>", z.read("word/document.xml"))


class DeckImageDiagramTests(unittest.TestCase):
    def test_deck_embeds_slide_image(self):
        import tempfile
        from pathlib import Path
        from reverseai.studio import embed_images
        ws = tempfile.mkdtemp()
        (Path(ws) / "assets").mkdir()
        (Path(ws) / "assets" / "s.png").write_bytes(_png(80, 60))
        spec = {"slides": [{"layout": "image", "title": "Pic", "image": "assets/s.png"}]}
        embed_images(spec, ws)
        data = generate("pptx", spec, name="deck").data
        z = zipfile.ZipFile(BytesIO(data))
        self.assertIsNone(z.testzip())
        self.assertTrue(any("media/image" in n for n in z.namelist()))
        self.assertIn(b"<p:pic>", z.read("ppt/slides/slide1.xml"))

    def test_diagram_shapes_render(self):
        spec = {"slides": [{"layout": "diagram", "title": "Flow", "shapes": [
            {"type": "roundrect", "x": 5, "y": 30, "w": 20, "h": 18, "text": "A"},
            {"type": "arrow", "x": 25, "y": 39, "x2": 45, "y2": 39},
            {"type": "rect", "x": 45, "y": 30, "w": 20, "h": 18, "text": "B"}]}]}
        data = generate("pptx", spec, name="diag").data
        z = zipfile.ZipFile(BytesIO(data))
        self.assertIsNone(z.testzip())
        slide = z.read("ppt/slides/slide1.xml")
        self.assertIn(b"prst=\"line\"", slide)
        self.assertIn(b"tailEnd", slide)

    def test_animation_adds_timing_but_stays_valid(self):
        data = generate("pptx", {"animate": True, "slides": [
            {"title": "x", "bullets": ["a", "b"]}]}, name="anim").data
        z = zipfile.ZipFile(BytesIO(data))
        self.assertIsNone(z.testzip())
        self.assertIn(b"<p:timing>", z.read("ppt/slides/slide1.xml"))
