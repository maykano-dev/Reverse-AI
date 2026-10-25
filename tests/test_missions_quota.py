"""Mission persistence/resume and per-token quotas."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.missions import MissionStore, MissionStoreError  # noqa: E402
from reverseai.security.quota import (  # noqa: E402
    QuotaError, QuotaPolicy, QuotaTracker,
)


class MissionTests(unittest.TestCase):
    def test_save_load_checkpoint_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            store = MissionStore(td)
            mission = {"id": "mission_abc", "objective": "modernise",
                       "status": "planned", "phases": ["scope", "verify"]}
            store.save(mission)
            loaded = store.load("mission_abc")
            self.assertEqual(loaded["objective"], "modernise")
            store.checkpoint("mission_abc", "scope agreed", status="running")
            resumed = store.resume("mission_abc")
            self.assertEqual(resumed["status"], "running")
            self.assertEqual(resumed["resume_count"], 1)
            self.assertTrue(store.list())

    def test_invalid_id_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(MissionStore(td).load("../../etc/passwd"))
            with self.assertRaises(MissionStoreError):
                MissionStore(td).save({"id": "../escape"})

    def test_terminal_mission_does_not_resume(self):
        with tempfile.TemporaryDirectory() as td:
            store = MissionStore(td)
            store.save({"id": "mission_done", "status": "done"})
            with self.assertRaises(MissionStoreError):
                store.resume("mission_done")


class QuotaTests(unittest.TestCase):
    def test_quota_allows_then_refuses(self):
        with tempfile.TemporaryDirectory() as td:
            tracker = QuotaTracker(Path(td) / "q.json",
                                   QuotaPolicy(runs_per_month=2,
                                               tokens_per_month=100,
                                               cost_usd_per_month=1.0))
            token = "secret-token"
            tracker.consume(token, runs=1, tokens=50, cost_usd=0.4)
            tracker.consume(token, runs=1, tokens=40, cost_usd=0.4)
            check = tracker.check(token, runs=1)
            self.assertFalse(check["allowed"])
            with self.assertRaises(QuotaError):
                tracker.consume(token, runs=1)

    def test_tokens_are_not_stored_in_plaintext(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "q.json"
            tracker = QuotaTracker(path)
            tracker.consume("super-secret-token", runs=1)
            self.assertNotIn("super-secret-token", path.read_text())
            self.assertIn("tokens", path.read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
