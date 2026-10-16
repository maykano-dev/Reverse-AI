"""HTTP control API tests — real server on an ephemeral port, real sockets.

Run: python3 -m unittest tests.test_server -v
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.job import Job  # noqa: E402
from reverseai.server.app import ReverseAIServer  # noqa: E402


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _post(url, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.srv = ReverseAIServer(host="127.0.0.1", port=0, store_dir=cls.tmp.name)
        cls.host, cls.port = cls.srv.address
        cls.base = f"http://{cls.host}:{cls.port}"
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def test_health(self):
        status, body = _get(f"{self.base}/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "ok")

    def test_caps(self):
        status, body = _get(f"{self.base}/caps")
        self.assertEqual(status, 200)
        self.assertIn("bubblewrap", body)

    def test_analyze(self):
        status, body = _post(f"{self.base}/analyze", {"path": "/usr/bin/objdump"})
        self.assertEqual(status, 200)
        self.assertEqual(body["fmt"], "elf")
        self.assertTrue(body["needed_libraries"])

    def test_analyze_missing_path(self):
        status, body = _post(f"{self.base}/analyze", {})
        self.assertEqual(status, 400)

    def test_analyze_bad_file(self):
        status, body = _post(f"{self.base}/analyze", {"path": "/no/such/file"})
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_jobs_empty_then_persisted(self):
        status, body = _get(f"{self.base}/jobs")
        self.assertEqual(status, 200)
        before = len(body["jobs"])
        # inject a saved job directly into the store
        job = Job(goal="demo")
        job.status = "completed"
        job.final_answer = "done"
        self.srv.store.save(job)
        status, body = _get(f"{self.base}/jobs")
        self.assertEqual(len(body["jobs"]), before + 1)
        # fetch it by id
        status, rec = _get(f"{self.base}/jobs/{job.id}")
        self.assertEqual(status, 200)
        self.assertEqual(rec["goal"], "demo")

    def test_job_not_found(self):
        status, body = _get(f"{self.base}/jobs/job_doesnotexist")
        self.assertEqual(status, 404)

    def test_run_job_requires_goal(self):
        status, body = _post(f"{self.base}/jobs", {})
        self.assertEqual(status, 400)

    def test_run_job_bad_provider_reports_error(self):
        # deepseek with no API key -> provider error surfaced as 400, not a crash
        import os
        if os.environ.get("DEEPSEEK_API_KEY"):
            self.skipTest("DEEPSEEK_API_KEY is set; cannot test the missing-key path")
        status, body = _post(f"{self.base}/jobs",
                             {"goal": "x", "provider": "deepseek"})
        self.assertEqual(status, 400)
        self.assertIn("provider error", body["error"])

    def test_not_found(self):
        status, body = _get(f"{self.base}/nope")
        self.assertEqual(status, 404)

    def test_serves_ui(self):
        with urllib.request.urlopen(f"{self.base}/", timeout=5) as r:
            html = r.read().decode()
        self.assertIn("<title>ReverseAI</title>", html)
        with urllib.request.urlopen(f"{self.base}/app.js", timeout=5) as r:
            self.assertEqual(r.status, 200)

    def test_start_and_stream_mock(self):
        # mock provider needs no key; empty script -> immediate final.
        status, body = _post(f"{self.base}/jobs/start",
                             {"goal": "say hi", "provider": "mock"})
        self.assertEqual(status, 200)
        job_id = body["job_id"]
        # drain the SSE stream and collect event types
        types = []
        with urllib.request.urlopen(f"{self.base}/jobs/{job_id}/events", timeout=10) as r:
            for raw in r:
                line = raw.decode().strip()
                if line.startswith("data:"):
                    import json as _j
                    ev = _j.loads(line[5:].strip())
                    types.append(ev["type"])
                    if ev["type"] in ("final", "error"):
                        break
        self.assertIn("start", types)
        self.assertTrue(types[-1] in ("final", "error"))

    def test_start_requires_goal(self):
        status, body = _post(f"{self.base}/jobs/start", {"provider": "mock"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
