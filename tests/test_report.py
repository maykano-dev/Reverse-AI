"""Signed verification report tests — JSON, HTML, signatures, HTTP routes.

Run: python3 -m unittest tests.test_report -v

No network. The HTTP test uses a real local server on an ephemeral port.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.evidence import Confidence  # noqa: E402
from reverseai.agent.job import Job  # noqa: E402
from reverseai.server.app import ReverseAIServer  # noqa: E402
from reverseai.verify import (  # noqa: E402
    build_report,
    render_html,
    render_json,
    verify_signature,
)

SHA = "a" * 64


def make_record() -> dict:
    job = Job(goal="Make the program print NEW instead of OLD.",
              target_path="/tmp/app")
    job.id = "job_reporttest01"
    job.status = "completed"
    job.created_at = 1_700_000_000.0
    job.finished_at = 1_700_000_010.0
    job.evidence.believed("The string OLD lives in .rodata", source="analysis")
    job.evidence.observed("applied 1 patch, 3 bytes changed", source="modify")
    job.evidence.verified("behavioral test passed: 1 input matched the expected delta",
                          source="verify_modification")
    job.artifact = "app-patcher-new-abc123.bin"
    job.artifact_meta = {"name": job.artifact, "size": 15920, "sha256": SHA,
                         "path": "/tmp/app-patcher-new-abc123.bin"}
    job.verification = {
        "verified": True,
        "passed_tests": 1,
        "tests_run": 1,
        "reason": "behavioral test passed",
        "attempts": [{
            "attempt": 1, "passed": True, "reason": "1 input(s): 1 matched, 1 differed; expected delta met",
            "report": {
                "summary": "2 input(s): 1 matched, 1 differed; expected delta met",
                "matched": ["default"],
                "differed": ["switch"],
                "unexpected": [],
                "expected_delta_met": True,
                "cases": [{
                    "name": "switch", "matched": False,
                    "differences": ["stdout"], "expected_met": True,
                    "unexpected": False,
                }],
            },
        }],
        "test_summary": {
            "summary": "2 input(s): 1 matched, 1 differed; expected delta met",
            "matched": ["default"], "differed": ["switch"],
            "unexpected": [], "expected_delta_met": True,
        },
    }
    job.delivery = {"allowed": True, "reason": "behavioral test passed"}
    job.differential = {
        "summary": "2 input(s): 1 matched, 1 differed; expected delta met",
        "matched": ["default"], "differed": ["switch"],
        "unexpected": [], "expected_delta_met": True,
    }
    job.sources = [{"url": "https://example.com/doc", "title": "Example"}]
    return job.to_dict()


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.record = make_record()
        self.report = build_report(self.record)

    def test_report_contains_artifact_and_all_tiers(self):
        r = self.report
        self.assertEqual(r["artifact"]["sha256"], SHA)
        self.assertEqual(r["artifact"]["size"], 15920)
        self.assertEqual(r["artifact"]["name"], self.record["artifact"])
        self.assertEqual(r["evidence_counts"],
                         {"believed": 1, "observed": 1, "verified": 1})
        self.assertEqual(r["evidence_tier"], "verified")
        self.assertEqual(r["tests_run"], 1)
        self.assertEqual(r["tests_passed"], 1)
        self.assertTrue(r["differential"]["expected_delta_met"])
        self.assertTrue(r["delivery"]["allowed"])

    def test_signature_is_deterministic_and_tamper_evident(self):
        self.assertTrue(verify_signature(self.report))
        again = build_report(self.record)
        self.assertEqual(self.report["signature"], again["signature"])

        for mutate in (
            lambda r: r.__setitem__("goal", "something else"),
            lambda r: r["artifact"].__setitem__("sha256", "b" * 64),
            lambda r: r["tests"][0].__setitem__("passed", False),
            lambda r: r["evidence_counts"].__setitem__("verified", 99),
            lambda r: r.__setitem__("generated_at", "2030-01-01T00:00:00Z"),
        ):
            altered = copy.deepcopy(self.report)
            mutate(altered)
            self.assertFalse(verify_signature(altered))

    def test_hmac_when_key_is_set(self):
        with mock.patch.dict(os.environ, {"REVERSEAI_REPORT_KEY": "report-secret"}):
            signed = build_report(self.record)
            self.assertEqual(signed["algorithm"], "HMAC-SHA256")
            self.assertTrue(verify_signature(signed))
            with mock.patch.dict(os.environ, {"REVERSEAI_REPORT_KEY": "wrong"}):
                self.assertFalse(verify_signature(signed))

    def test_standalone_differential_feeds_the_report(self):
        rec = make_record()
        rec["verification"] = {}
        rec["delivery"] = {"allowed": False, "reason": "no behavioral test"}
        rec["differential"] = {
            "summary": "1 input(s): 0 matched, 1 differed; 1 unexpected regression(s)",
            "matched": [], "differed": ["default"],
            "unexpected": ["default"], "expected_delta_met": False,
        }
        r = build_report(rec)
        self.assertEqual(r["differential"]["unexpected"], ["default"])
        self.assertEqual(r["evidence_tier"], "observed")
        self.assertFalse(r["delivery"]["allowed"])
        self.assertTrue(verify_signature(r))

    def test_json_roundtrip(self):
        raw = render_json(self.report)
        parsed = json.loads(raw)
        self.assertEqual(parsed["signature"], self.report["signature"])
        self.assertTrue(verify_signature(parsed))

    def test_html_is_self_contained(self):
        html = render_html(self.report)
        self.assertIn(SHA, html)
        self.assertIn("Verification report", html)
        for forbidden in ("<script", "<link", "http://", "https://", "@import",
                          "src="):
            self.assertNotIn(forbidden, html.lower())
        # Inline styling only; no network resource references.
        self.assertIn("<style>", html)


class ReportServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.srv = ReverseAIServer("127.0.0.1", 0, cls.tmp.name)
        cls.host, cls.port = cls.srv.address
        cls.base = f"http://{cls.host}:{cls.port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        # Save a completed job with a verification report.
        rec = make_record()
        job = Job(goal=rec["goal"], target_path=rec["target_path"])
        job.id = rec["id"]
        job.status = rec["status"]
        job.created_at = rec["created_at"]
        job.finished_at = rec["finished_at"]
        job.evidence.add("a", Confidence.BELIEVED)
        job.evidence.add("b", Confidence.OBSERVED)
        job.evidence.add("c", Confidence.VERIFIED)
        job.artifact = rec["artifact"]
        job.artifact_meta = rec["artifact_meta"]
        job.verification = rec["verification"]
        job.delivery = rec["delivery"]
        cls.srv.store.save(job)
        cls.job_id = job.id

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def test_json_report_route(self):
        with urllib.request.urlopen(
                f"{self.base}/jobs/{self.job_id}/report", timeout=6) as r:
            self.assertEqual(r.status, 200)
            body = json.loads(r.read())
            self.assertIn("application/json", r.headers.get("Content-Type", ""))
        self.assertEqual(body["artifact"]["sha256"], SHA)
        self.assertTrue(verify_signature(body))
        self.assertEqual(body["evidence_counts"]["verified"], 1)

    def test_html_report_route(self):
        with urllib.request.urlopen(
                f"{self.base}/jobs/{self.job_id}/report.html", timeout=6) as r:
            self.assertEqual(r.status, 200)
            html = r.read().decode()
            self.assertIn("text/html", r.headers.get("Content-Type", ""))
        self.assertIn(SHA, html)
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("https://", html.lower())

    def test_missing_report_404(self):
        try:
            urllib.request.urlopen(f"{self.base}/jobs/job_missing/report", timeout=5)
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 404)
            exc.close()
        else:
            self.fail("expected 404")


if __name__ == "__main__":
    unittest.main(verbosity=2)
