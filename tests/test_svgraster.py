"""Tests for SVG normalization before rasterization (no external tools needed)."""

from __future__ import annotations

import unittest

from reverseai.docgen.svgraster import _ensure_svg_attrs


class EnsureSvgAttrsTests(unittest.TestCase):
    def test_injects_xmlns_when_missing(self):
        out = _ensure_svg_attrs('<svg><circle r="10"/></svg>')
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', out)
        self.assertIn("<circle", out)

    def test_adds_viewbox_when_no_dimensions(self):
        out = _ensure_svg_attrs('<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>')
        self.assertIn("viewBox=", out)

    def test_keeps_existing_viewbox_and_xmlns(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><rect/></svg>'
        self.assertEqual(_ensure_svg_attrs(svg), svg)

    def test_keeps_width_height_without_adding_viewbox(self):
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="400"><rect/></svg>'
        out = _ensure_svg_attrs(svg)
        self.assertNotIn("viewBox", out)

    def test_non_svg_passthrough(self):
        self.assertEqual(_ensure_svg_attrs("not svg"), "not svg")


if __name__ == "__main__":
    unittest.main()
