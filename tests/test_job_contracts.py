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
        job.surfaces = [{"id": "sf_demo", "kind": "question",
                         "title": "Pick a path"}]
        job.preview = "site/index.html"
        report = build_report(job.to_dict())
        self.assertEqual(report["world_model"]["nodes"], 4)
        self.assertEqual(report["test_strength"]["mutation_score"], 0.75)
        self.assertEqual(report["surfaces"][0]["title"], "Pick a path")
        html = render_html(report)
        self.assertIn("World model", html)
        self.assertIn("0.75", html)
        self.assertIn("Interactive surfaces", html)
        self.assertIn("Pick a path", html)

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

    def test_history_summaries_identify_the_conversation(self):
        with tempfile.TemporaryDirectory() as td:
            store = JobStore(td)
            first = Job(goal="hello", conversation_id="conv_one")
            second = Job(goal="how are you", conversation_id="conv_one")
            store.save(first)
            store.save(second)
            rows = store.list_summaries()
            self.assertEqual(len(rows), 2)
            self.assertEqual({r["conversation_id"] for r in rows}, {"conv_one"})

    def test_surface_history_prefers_the_answered_state(self):
        with tempfile.TemporaryDirectory() as td:
            store = JobStore(td)
            first = Job(goal="hello", conversation_id="conv_surfaces")
            first.surfaces = [{"id": "sf_one", "created_at": 2.0,
                               "title": "Pick", "status": "pending"}]
            second = Job(goal="next", conversation_id="conv_surfaces")
            answered = dict(first.surfaces[0])
            answered["status"] = "submitted"
            second.surfaces = [answered]
            store.save(first)
            store.save(second)
            rows = store.surfaces_for_conversation("conv_surfaces")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "submitted")

    def test_conversation_summary_collapses_turns(self):
        with tempfile.TemporaryDirectory() as td:
            store = JobStore(td)
            first = Job(goal="hello", conversation_id="conv_one",
                        created_at=100.0)
            second = Job(goal="how are you", conversation_id="conv_one",
                         created_at=200.0)
            store.save(first)
            store.save(second)
            rows = store.list_conversations()
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["goal"], "hello")
            self.assertEqual(row["latest_goal"], "how are you")
            self.assertEqual(row["id"], second.id)
            self.assertEqual(row["turns"], 2)
            self.assertEqual(row["ids"], [second.id, first.id])


if __name__ == "__main__":
    unittest.main(verbosity=2)
