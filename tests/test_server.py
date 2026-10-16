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

    def test_config_ready_flag(self):
        status, body = _get(f"{self.base}/config")
        self.assertEqual(status, 200)
        self.assertIn("ready", body)
        self.assertIsInstance(body["ready"], bool)

    def test_api_modify_and_download(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "data.bin"
            src.write_bytes(b"HELLO")
            s, b = _post(f"{self.base}/modify", {"target": str(src),
                         "patches": [{"offset": 0, "hex": "4a"}]})  # H -> J
            self.assertEqual(s, 200, b)
            self.assertIn("download", b)
            self.assertEqual(b["bytes_changed"], 1)
            # download the modified file
            with urllib.request.urlopen(f"{self.base}{b['download']}", timeout=5) as r:
                self.assertEqual(r.read()[0:1], b"J")

    def test_api_modify_bad_request(self):
        s, b = _post(f"{self.base}/modify", {"target": "/x"})
        self.assertEqual(s, 400)

    def test_api_verify_requires_both(self):
        s, b = _post(f"{self.base}/verify", {"original": "/a"})
        self.assertEqual(s, 400)

    def test_api_clone_refuses_internal(self):
        s, b = _post(f"{self.base}/clone", {"url": "http://127.0.0.1:1/"})
        self.assertEqual(s, 400)
        self.assertIn("error", b)

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

    def test_upload_and_kind(self):
        data = b"\x7fELF" + b"\x00" * 200
        req = urllib.request.Request(f"{self.base}/upload", data=data,
                                     headers={"X-Filename": "mal ware!.bin"}, method="PUT")
        with urllib.request.urlopen(req, timeout=10) as r:
            body = json.loads(r.read())
        self.assertEqual(body["kind"], "elf")
        self.assertTrue(body["path"].endswith(".bin"))
        self.assertEqual(body["filename"], "mal_ware_.bin")  # sanitized
        self.assertTrue(Path(body["path"]).exists())

    def test_artifact_404_without_one(self):
        status, body = _get(f"{self.base}/conversations/conv_none/artifact")
        self.assertEqual(status, 404)

    def test_job_artifact_persist_and_download(self):
        job = Job(goal="deliver")
        job.status = "completed"
        self.srv.store.save(job)
        # stage a delivered file and persist it for this job
        with tempfile.TemporaryDirectory() as d:
            art = Path(d) / "app.patched"
            art.write_bytes(b"PATCHED-BINARY-BYTES")
            saved = self.srv.store.save_artifact(job.id, str(art))
            self.assertIsNotNone(saved)
        # download via the durable job endpoint
        with urllib.request.urlopen(f"{self.base}/jobs/{job.id}/artifact", timeout=5) as r:
            self.assertEqual(r.read(), b"PATCHED-BINARY-BYTES")
            self.assertIn("app.patched", r.headers.get("Content-Disposition", ""))

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

    def test_start_returns_conversation_id_and_reuses(self):
        s1, b1 = _post(f"{self.base}/jobs/start", {"goal": "a", "provider": "mock"})
        self.assertEqual(s1, 200)
        cid = b1["conversation_id"]
        self.assertTrue(cid and cid.startswith("conv_"))
        # follow-up with the same conversation id must be accepted
        s2, b2 = _post(f"{self.base}/jobs/start",
                       {"goal": "b", "conversation_id": cid})
        self.assertEqual(s2, 200)
        self.assertEqual(b2["conversation_id"], cid)
        self.assertNotEqual(b2["job_id"], b1["job_id"])  # distinct turns


class RunManagerEvictionTests(unittest.TestCase):
    def test_runs_are_bounded(self):
        from reverseai.agent.store import JobStore
        from reverseai.server import runs as runs_mod
        from reverseai.server.runs import Run, RunManager

        with tempfile.TemporaryDirectory() as d:
            rm = RunManager(JobStore(d))
            # stuff more finished runs than the cap and trigger eviction
            for i in range(runs_mod._MAX_RUNS + 50):
                r = Run(job_id=f"job_{i:08x}")
                r.done.set()
                rm._runs[r.job_id] = r
            rm._evict()
            self.assertLessEqual(len(rm._runs), runs_mod._MAX_RUNS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
