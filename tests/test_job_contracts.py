"""Job serialization remains additive and stable."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.job import Job  # noqa: E402
from reverseai.agent.store import JobStore  # noqa: E402
from reverseai.verify.report import build_report, render_html  # noqa: E402


class JobContractTests(unittest.TestCase):
    def test_new_fields_serialize_without_breaking_old_ones(self):
        job = Job(goal="inspect", target_path="x")
        job.world_model = {"nodes": 4, "edges": 3}
        job.opportunities = [{"title": "look here"}]
        job.hypotheses = [{"statement": "a causes b"}]
        job.test_strength = {"mutation_score": 0.8}
        data = job.to_dict()
        for key in ("goal", "evidence", "verification", "delivery",
                    "world_model", "opportunities", "hypotheses",
                    "test_strength"):
            self.assertIn(key, data)
        self.assertEqual(data["world_model"]["nodes"], 4)
        json.dumps(data)

    def test_report_includes_intelligence_evidence(self):
        job = Job(goal="inspect", target_path="x", status="completed")
        job.world_model = {"nodes": 4, "unresolved": 2}
        job.test_strength = {"mutation_score": 0.75}
        report = build_report(job.to_dict())
        self.assertEqual(report["world_model"]["nodes"], 4)
        self.assertEqual(report["test_strength"]["mutation_score"], 0.75)
        html = render_html(report)
        self.assertIn("World model", html)
        self.assertIn("0.75", html)

    def test_store_round_trip_keeps_fields(self):
        with tempfile.TemporaryDirectory() as td:
            store = JobStore(td)
            job = Job(goal="inspect")
            job.world_model = {"nodes": 1}
            job.test_strength = {"mutation_score": 1.0}
            store.save(job)
            data = store.get(job.id)
            self.assertEqual(data["world_model"]["nodes"], 1)
            self.assertEqual(data["test_strength"]["mutation_score"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
