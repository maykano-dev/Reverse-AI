"""`.env` loader tests.

Run: python3 -m unittest tests.test_config -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.config import load_dotenv  # noqa: E402


class LoadDotenvTests(unittest.TestCase):
    def _write(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / ".env"
        p.write_text(text)
        return p

    def test_basic_and_comments_and_quotes(self):
        p = self._write('A=1\n# note\n\nB="two"\nC=\'three\'\n')
        for k in ("A", "B", "C"):
            os.environ.pop(k, None)
        try:
            n = load_dotenv(p)
            self.assertEqual(n, 3)
            self.assertEqual(os.environ["A"], "1")
            self.assertEqual(os.environ["B"], "two")
            self.assertEqual(os.environ["C"], "three")
        finally:
            for k in ("A", "B", "C"):
                os.environ.pop(k, None)

    def test_does_not_override_existing(self):
        os.environ["KEEP_ME"] = "original"
        p = self._write("KEEP_ME=changed\n")
        try:
            load_dotenv(p)
            self.assertEqual(os.environ["KEEP_ME"], "original")
            load_dotenv(p, override=True)
            self.assertEqual(os.environ["KEEP_ME"], "changed")
        finally:
            os.environ.pop("KEEP_ME", None)

    def test_missing_file_is_noop(self):
        self.assertEqual(load_dotenv("/no/such/.env"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
