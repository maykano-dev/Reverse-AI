"""Browsing-proxy tests (local fixture, no real internet).

Run: python3 -m unittest tests.test_proxy -v
"""

from __future__ import annotations

import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.clone.proxy import ProxyError, fetch, rewrite_html  # noqa: E402

PAGE = (b"<!DOCTYPE html><html><head><title>Hi</title></head>"
        b"<body><a href=\"/about\">About</a> "
        b"<a href=\"https://ext.example.com/x\">Ext</a> "
        b"<a href=\"#top\">Top</a></body></html>")


class _Fx(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("X-Frame-Options", "DENY")  # we must override this
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)


class RewriteTests(unittest.TestCase):
    def test_injects_base_and_proxifies_links(self):
        html = rewrite_html(PAGE.decode(), "https://site.test/page")
        self.assertIn('<base href="https://site.test/page">', html)
        # relative + absolute links routed through the proxy
        self.assertEqual(html.count("/proxy?url="), 2)  # /about and the ext link
        # anchor link left alone
        self.assertIn('href="#top"', html)


class FetchTests(unittest.TestCase):
    def test_refuses_internal_host(self):
        with self.assertRaises(ProxyError):
            fetch("http://127.0.0.1:1/")   # allow_private defaults False

    def test_bad_scheme(self):
        with self.assertRaises(ProxyError):
            fetch("file:///etc/passwd", allow_private=True)

    def test_fetch_local_fixture(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Fx)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            data, ctype, final = fetch(f"http://127.0.0.1:{port}/", allow_private=True)
            self.assertIn(b"<title>Hi</title>", data)
            self.assertIn("text/html", ctype)
        finally:
            srv.shutdown(); srv.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
