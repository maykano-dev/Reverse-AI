"""Dev-server preview manager: gate, sandbox start/stop, and validation."""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.sandbox.backends.bubblewrap import BubblewrapSandbox  # noqa: E402
from reverseai.server.preview_server import (  # noqa: E402
    PreviewServerError, PreviewServerManager,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class PreviewServerTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REVERSEAI_ALLOW_PREVIEW_SERVER", None)
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaises(PreviewServerError) as ctx:
                    PreviewServerManager().start(
                        "conv_x", td, "python3 -m http.server 3001", 3001)
        self.assertIn("disabled", str(ctx.exception))

    def test_rejects_invalid_port(self):
        with patch.dict(os.environ, {"REVERSEAI_ALLOW_PREVIEW_SERVER": "1"}):
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaises(PreviewServerError):
                    PreviewServerManager().start(
                        "conv_x", td, "python3 -m http.server 80", 80)

    @unittest.skipUnless(BubblewrapSandbox.is_available(),
                         "bubblewrap/user namespaces unavailable")
    def test_starts_and_stops_a_real_server_in_bubblewrap(self):
        port = _free_port()
        with tempfile.TemporaryDirectory() as td:
            Path(td, "index.html").write_text("<h1>dev preview</h1>")
            manager = PreviewServerManager()
            with patch.dict(os.environ, {"REVERSEAI_ALLOW_PREVIEW_SERVER": "1"}):
                try:
                    info = manager.start(
                        "conv_test", td,
                        f"{sys.executable} -m http.server {{port}} --bind 127.0.0.1",
                        port)
                    self.assertTrue(info["running"])
                    with urllib.request.urlopen(info["url"], timeout=5) as r:
                        self.assertIn("dev preview", r.read().decode())
                finally:
                    manager.stop("conv_test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
