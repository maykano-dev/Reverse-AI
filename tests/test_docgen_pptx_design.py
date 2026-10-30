"""Designed PPTX: themes, layouts, colors, and shapes - still valid OOXML."""

import unittest
import zipfile
from io import BytesIO

from reverseai.docgen import generate
from reverseai.docgen.pptx import PRESETS, resolve_theme


class ThemeTests(unittest.TestCase):
    def test_preset_by_name(self):
        t = resolve_theme("midnight")
        self.assertEqual(t["bg"], PRESETS["midnight"]["bg"])
        self.assertIn("fonts", t)

    def test_custom_colors_override(self):
        t = resolve_theme({"preset": "midnight", "accent": "#FF0000",
                           "fonts": {"title": "Futura"}})
        self.assertEqual(t["accent"], "FF0000")
        self.assertEqual(t["fonts"]["title"], "Futura")

    def test_bad_color_falls_back(self):
        t = resolve_theme({"accent": "nothex"})
        self.assertEqual(t["accent"], PRESETS["light"]["accent"])


class DesignedDeckTests(unittest.TestCase):
    def _zip(self, data):
        return zipfile.ZipFile(BytesIO(data))

    def test_dark_theme_applies_background(self):
        data = generate("pptx", {"theme": "midnight", "slides": [
            {"layout": "cover", "title": "Hi", "subtitle": "there"}]}).data
        z = self._zip(data)
        slide = z.read("ppt/slides/slide1.xml").decode()
        self.assertIn(PRESETS["midnight"]["bg"], slide)  # bg color present
        self.assertIn("<p:bg>", slide)

    def test_all_layouts_render_valid(self):
        spec = {"theme": "aurora", "slides": [
            {"layout": "cover", "title": "T", "subtitle": "s"},
            {"layout": "section", "title": "Sec"},
            {"layout": "content", "title": "C", "bullets": ["a", "b"]},
            {"layout": "two-column", "title": "TC", "columns": [["x"], ["y"]]},
            {"layout": "quote", "quote": "q", "attribution": "me"},
            {"layout": "statement", "title": "Big"},
        ]}
        data = generate("pptx", spec).data
        z = self._zip(data)
        self.assertIsNone(z.testzip())
        self.assertEqual(len([n for n in z.namelist()
                              if n.startswith("ppt/slides/slide") and n.endswith(".xml")]), 6)


    def test_cards_layout(self):
        data = generate("pptx", {"slides": [{"layout": "cards", "title": "R", "cards": [
            {"num": "01", "title": "A"}, {"num": "02", "title": "B"},
            {"num": "03", "title": "C"}]}]}).data
        z = self._zip(data)
        self.assertIsNone(z.testzip())
        slide = z.read("ppt/slides/slide1.xml")
        self.assertEqual(slide.count(b"roundRect"), 3)
    def test_per_slide_bg_override(self):
        data = generate("pptx", {"slides": [
            {"title": "x", "bg": "#123456", "bullets": ["y"]}]}).data
        slide = self._zip(data).read("ppt/slides/slide1.xml").decode()
        self.assertIn("123456", slide)

    def test_custom_font_in_theme_part(self):
        data = generate("pptx", {"theme": {"fonts": {"title": "Futura"}},
                                 "slides": [{"title": "x"}]}).data
        theme = self._zip(data).read("ppt/theme/theme1.xml").decode()
        self.assertIn("Futura", theme)


if __name__ == "__main__":
    unittest.main()
