"""Authentication and path-boundary tests for the HTTP API."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.server.app import ReverseAIServer  # noqa: E402

TOKEN = "test-token-" + "x" * 20


def _request(url: str, *, payload: dict | None = None,
             token: str | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        finally:
            e.close()


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.old_token = os.environ.get("REVERSEAI_AUTH_TOKEN")
        cls.old_roots = os.environ.get("REVERSEAI_ALLOWED_ROOTS")
        os.environ["REVERSEAI_AUTH_TOKEN"] = TOKEN
        os.environ["REVERSEAI_ALLOWED_ROOTS"] = str(cls.root)
        cls.srv = ReverseAIServer(host="127.0.0.1", port=0,
                                  store_dir=str(cls.root / "store"))
        cls.host, cls.port = cls.srv.address
        cls.base = f"http://{cls.host}:{cls.port}"
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.thread.join(timeout=3)
        if cls.old_token is None:
            os.environ.pop("REVERSEAI_AUTH_TOKEN", None)
        else:
            os.environ["REVERSEAI_AUTH_TOKEN"] = cls.old_token
        if cls.old_roots is None:
            os.environ.pop("REVERSEAI_ALLOWED_ROOTS", None)
        else:
            os.environ["REVERSEAI_ALLOWED_ROOTS"] = cls.old_roots
        cls.tmp.cleanup()

    def test_public_health_and_config(self):
        self.assertEqual(_request(self.base + "/health")[0], 200)
        self.assertEqual(_request(self.base + "/config")[0], 200)

    def test_api_requires_a_token(self):
        for path in ("/jobs", "/caps", "/capabilities", "/templates"):
            status, body = _request(self.base + path)
            self.assertEqual(status, 401, path)
            self.assertIn("error", body)

    def test_valid_token_opens_the_api(self):
        status, body = _request(self.base + "/jobs", token=TOKEN)
        self.assertEqual(status, 200)
        self.assertIn("jobs", body)
        status, body = _request(self.base + "/surfaces", token=TOKEN)
        self.assertEqual(status, 200)
        self.assertIn("desktop", body)
        self.assertFalse(body["payments"]["live_provider"])
        self.assertFalse(body["desktop"]["input_injection"])

    def test_wrong_token_is_refused(self):
        status, _ = _request(self.base + "/jobs", token="wrong")
        self.assertEqual(status, 401)

    def test_query_token_is_accepted(self):
        status, body = _request(self.base + "/jobs?token=" + TOKEN)
        self.assertEqual(status, 200)
        self.assertIn("jobs", body)

    def test_world_and_discover_path_guard(self):
        inside = self.root / "sample"
        inside.write_bytes(b"MZ" + b"\x00" * 100)
        status, body = _request(self.base + "/world", payload={"path": str(inside)},
                                token=TOKEN)
        self.assertEqual(status, 200, body)
        status, body = _request(self.base + "/discover",
                                payload={"path": str(inside)}, token=TOKEN)
        self.assertEqual(status, 200, body)
        outside = "/etc/hosts"
        status, body = _request(self.base + "/world", payload={"path": outside},
                                token=TOKEN)
        self.assertEqual(status, 403, body)
        status, body = _request(self.base + "/discover",
                                payload={"path": outside}, token=TOKEN)
        self.assertEqual(status, 403, body)

    def test_traversal_job_id_is_not_found(self):
        status, body = _request(self.base + "/jobs/../../etc/passwd", token=TOKEN)
        self.assertIn(status, (404, 400))
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
