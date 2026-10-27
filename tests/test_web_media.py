"""Image discovery and web-resource installation, without network access."""

from __future__ import annotations

import html
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.builtins import WebImagesTool  # noqa: E402
from reverseai.agent.research import (  # noqa: E402
    ImageResult, images_from_html, parse_bing_images, parse_commons_images,
)
from reverseai.agent.tools import ToolContext  # noqa: E402


class ImageParsingTests(unittest.TestCase):
    def test_bing_result_json_is_unpacked(self):
        item = {
            "murl": "https://example.com/port.jpg",
            "turl": "https://example.com/port-thumb.jpg",
            "purl": "https://example.com/port",
            "t": "Tema port",
            "desc": "A container terminal in Tema",
        }
        page = f'<a m="{html.escape(json.dumps(item), quote=True)}"></a>'
        rows = parse_bing_images(page, 3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].image_url, "https://example.com/port.jpg")
        self.assertEqual(rows[0].page_url, "https://example.com/port")
        self.assertEqual(rows[0].title, "Tema port")

    def test_page_images_use_og_and_largest_srcset(self):
        page = b'''<html><head>
        <meta property="og:image" content="/hero.jpg">
        </head><body>
        <img srcset="small.jpg 400w, large.jpg 1600w" alt="Crane">
        </body></html>'''
        rows = images_from_html(page, "https://example.com/page")
        urls = [r.image_url for r in rows]
        self.assertIn("https://example.com/hero.jpg", urls)
        self.assertIn("https://example.com/large.jpg", urls)

    def test_commons_metadata_is_kept(self):
        payload = {"query": {"pages": {"1": {
            "title": "File:Tema Port.jpg", "index": 1,
            "imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/tema.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Tema_Port.jpg",
                "thumbwidth": 1200, "thumbheight": 800,
                "extmetadata": {
                    "Artist": {"value": "<a>Jane Doe</a>"},
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    "ImageDescription": {"value": "Tema harbour"},
                },
            }],
        }}}}
        rows = parse_commons_images(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].creator, "Jane Doe")
        self.assertEqual(rows[0].license, "CC BY-SA 4.0")
        self.assertEqual(rows[0].width, 1200)


class ImageToolTests(unittest.TestCase):
    def test_tool_returns_image_urls_and_sources(self):
        row = ImageResult(
            title="Tema port", image_url="https://example.com/port.jpg",
            page_url="https://example.com/port", snippet="A container terminal",
            source="bing")
        with tempfile.TemporaryDirectory() as td:
            ctx = ToolContext(job_id="t", workspace=td, goal="find an image")
            with patch("reverseai.agent.research.search_images",
                       return_value=[row]):
                res = WebImagesTool().run({"query": "Tema port"}, ctx)
        self.assertTrue(res.ok, res.content)
        self.assertIn("https://example.com/port.jpg", res.content)
        self.assertEqual(res.data["images"][0]["image_url"],
                         "https://example.com/port.jpg")
        self.assertEqual(res.data["sources"][0]["url"],
                         "https://example.com/port")


if __name__ == "__main__":
    unittest.main(verbosity=2)
