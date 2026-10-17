"""strip_dashes tests.

Run: python3 -m unittest tests.test_text -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.util.text import strip_dashes  # noqa: E402


class StripDashesTests(unittest.TestCase):
    def test_em_dash_to_comma(self):
        self.assertEqual(strip_dashes("I can help, but — first, context."),
                         "I can help, but, first, context.")

    def test_hyphen_join_to_space(self):
        self.assertEqual(strip_dashes("a general-purpose x86-64 tool"),
                         "a general purpose x86 64 tool")

    def test_markdown_bullets_preserved(self):
        out = strip_dashes("Steps:\n- first\n- second item")
        self.assertIn("\n- first", out)
        self.assertIn("\n- second item", out)

    def test_code_preserved(self):
        self.assertEqual(strip_dashes("run `a-b --flag` now — ok"),
                         "run `a-b --flag` now, ok")

    def test_fenced_code_preserved(self):
        src = "text — here\n```\nx = a-b-c\n```\nmore — text"
        out = strip_dashes(src)
        self.assertIn("x = a-b-c", out)      # code untouched
        self.assertIn("text, here", out)      # prose de-dashed
        self.assertIn("more, text", out)

    def test_empty(self):
        self.assertEqual(strip_dashes(""), "")
        self.assertEqual(strip_dashes(None), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
