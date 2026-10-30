"""Data-driven chart SVG generation and embedding."""

import tempfile
import unittest
import zipfile
from io import BytesIO

from reverseai.docgen import generate
from reverseai.docgen.charts import render_chart


class ChartSvgTests(unittest.TestCase):
    def test_bar_chart_svg(self):
        svg = render_chart({"type": "bar", "title": "T",
                            "data": [{"label": "A", "value": 3},
                                     {"label": "B", "value": 7}]})
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("<rect", svg)
        self.assertIn("</svg>", svg)

    def test_donut_chart_svg(self):
        svg = render_chart({"type": "donut",
                            "data": [{"label": "X", "value": 60},
                                     {"label": "Y", "value": 40}]})
        self.assertIn("<path", svg)
        self.assertIn("%", svg)        # legend percentages

    def test_line_chart_svg(self):
        svg = render_chart({"type": "line",
                            "series": [{"name": "s", "data": [1, 2, 3, 2, 4]}]})
        self.assertIn("<path", svg)

    def test_empty_chart_is_empty(self):
        self.assertEqual(render_chart({"type": "bar", "data": []}), "")

    def test_chart_embeds_in_deck(self):
        from reverseai.docgen.svgraster import available
        from reverseai.studio import embed_images
        if not available():
            self.skipTest("no SVG rasterizer")
        spec = {"slides": [{"title": "Rev", "chart": {
            "type": "bar", "data": [{"label": "Q1", "value": 5},
                                    {"label": "Q2", "value": 9}]}}]}
        embed_images(spec, tempfile.mkdtemp())
        self.assertIsInstance(spec["slides"][0].get("image_data"), (bytes, bytearray))
        z = zipfile.ZipFile(BytesIO(generate("pptx", spec).data))
        self.assertTrue(any("media/image" in n for n in z.namelist()))


if __name__ == "__main__":
    unittest.main()
