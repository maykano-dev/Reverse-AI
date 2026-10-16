"""Website-clone tests — against a local fixture server, no real internet.

Run: python3 -m unittest tests.test_clone -v
"""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.clone.web import CloneError, _rename, clone_site  # noqa: E402

PAGE = b"""<!DOCTYPE html><html><head><title>Acme Store</title>
<link rel="stylesheet" href="/style.css">
</head><body><h1>Welcome to Acme</h1>
<img src="/logo.png"><script src="/app.js"></script>
<img src="https://other.example.com/ext.png">
<a href="https://other.example.com/x">offsite</a></body></html>"""
CSS = b"body{background:#111;color:#fff;animation:fade 1s}"
JS = b"console.log('acme');"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


class _Fixture(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = {"/": PAGE, "/style.css": CSS, "/app.js": JS, "/logo.png": PNG}.get(self.path)
        if body is None:
            self.send_response(404); self.end_headers(); return
        ctype = ("text/html" if self.path == "/" else
                 "text/css" if self.path.endswith(".css") else
                 "application/javascript" if self.path.endswith(".js") else "image/png")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class RenameTests(unittest.TestCase):
    def test_case_preserving_rename(self):
        out, n = _rename("Acme ACME acme", "acme", "johndoemall")
        self.assertEqual(n, 3)
        self.assertIn("Johndoemall", out)
        self.assertIn("JOHNDOEMALL", out)
        self.assertIn("johndoemall", out)


class SSRFTests(unittest.TestCase):
    def test_refuses_internal_host_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(CloneError):
                clone_site("http://127.0.0.1:1/", d)  # allow_private defaults False

    def test_refuses_bad_scheme(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(CloneError):
                clone_site("file:///etc/passwd", d, allow_private=True)


class CloneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), _Fixture)
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def test_clone_with_assets_and_rename(self):
        with tempfile.TemporaryDirectory() as d:
            res = clone_site(f"http://127.0.0.1:{self.port}/", d,
                             rename_from="Acme", rename_to="johndoemall",
                             allow_private=True)
            self.assertEqual(res.assets, 3)          # css, png, js (same-origin)
            self.assertGreaterEqual(res.renamed, 2)  # title + heading
            html = (Path(d) / "index.html").read_text()
            self.assertIn("Johndoemall", html)       # heading capitalisation kept
            self.assertIn('assets/', html)           # references rewritten to local
            self.assertNotIn('href="/style.css"', html)
            # off-site asset left alone (not downloaded)
            self.assertTrue(any("other.example.com" in s for s in res.skipped))
            # downloaded files exist
            self.assertTrue(list((Path(d) / "assets").glob("*style.css")) or
                            list((Path(d) / "assets").glob("*_*")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
