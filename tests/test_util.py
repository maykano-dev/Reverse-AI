"""Logging/redaction tests.

Run: python3 -m unittest tests.test_util -v
"""

from __future__ import annotations

import logging
import sys
import unittest
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.util.logging import Redactor, _RedactingFormatter  # noqa: E402


class RedactorTests(unittest.TestCase):
    def test_scrubs_sk_key(self):
        r = Redactor()
        out = r.scrub("using key sk-abcDEF123456789 now")
        self.assertNotIn("sk-abcDEF123456789", out)
        self.assertIn("redacted", out)

    def test_scrubs_bearer(self):
        r = Redactor()
        out = r.scrub("Authorization: Bearer abc.def.ghi12345")
        self.assertNotIn("abc.def.ghi12345", out)

    def test_scrubs_env_literal(self):
        import os

        os.environ["DEEPSEEK_API_KEY"] = "supersecretvalue123"
        try:
            r = Redactor()
            out = r.scrub("the key is supersecretvalue123 ok")
            self.assertNotIn("supersecretvalue123", out)
        finally:
            del os.environ["DEEPSEEK_API_KEY"]

    def test_scrubs_github_token(self):
        r = Redactor()
        out = r.scrub("token ghp_0123456789abcdefghij extra")
        self.assertNotIn("ghp_0123456789abcdefghij", out)

    def test_benign_text_untouched(self):
        r = Redactor()
        text = "analyzed /usr/bin/ls — 3 sections, entropy 6.1"
        self.assertEqual(r.scrub(text), text)


class FormatterTests(unittest.TestCase):
    def test_formatter_redacts_in_log_output(self):
        logger = logging.getLogger("reverseai.test.redact")
        logger.handlers.clear()
        buf = StringIO()
        h = logging.StreamHandler(buf)
        h.setFormatter(_RedactingFormatter("%(message)s"))
        logger.addHandler(h)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.info("calling api with sk-TOPSECRETtoken999")
        self.assertNotIn("sk-TOPSECRETtoken999", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
