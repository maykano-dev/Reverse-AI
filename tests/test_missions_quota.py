"""Mission persistence/resume and per-token quotas."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.mission_worker import run_once  # noqa: E402
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

    def test_recovery_after_process_restart(self):
        with tempfile.TemporaryDirectory() as td:
            first = MissionStore(td)
            first.save({"id": "mission_restart", "status": "planned",
                        "objective": "resume me"})
            first.checkpoint("mission_restart", "analysis complete",
                             status="running")
            del first
            second = MissionStore(td)
            loaded = second.load("mission_restart")
            self.assertEqual(loaded["status"], "running")
            self.assertEqual(loaded["checkpoints"][-1]["note"],
                             "analysis complete")
            self.assertEqual(second.resume("mission_restart")["resume_count"], 1)

    def test_worker_lease_blocks_a_second_worker_until_expiry(self):
        with tempfile.TemporaryDirectory() as td:
            store = MissionStore(td)
            store.save({"id": "mission_lease", "status": "planned"})
            store.claim("mission_lease", "worker-a", lease_s=60, now=1000)
            with self.assertRaises(MissionStoreError):
                store.claim("mission_lease", "worker-b", lease_s=60, now=1001)
            store.claim("mission_lease", "worker-a", lease_s=60, now=1001)
            store.claim("mission_lease", "worker-a", lease_s=60, now=1061)
            store.release("mission_lease", "worker-a", status="paused")
            self.assertEqual(store.load("mission_lease")["status"], "paused")

    def test_worker_runs_a_due_mission_once(self):
        class Result:
            id = "job_worker"
            status = "completed"
        with tempfile.TemporaryDirectory() as td:
            store = MissionStore(td)
            store.save({"id": "mission_due", "status": "planned",
                        "objective": "finish", "phases": []})
            results = run_once(store, lambda goal: Result(), owner="worker-a")
            self.assertEqual(results[0]["status"], "done")
            self.assertEqual(store.load("mission_due")["last_job"], "job_worker")
            self.assertIsNone(store.load("mission_due").get("lease_owner"))

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

    def test_reservations_prevent_concurrent_overrun(self):
        with tempfile.TemporaryDirectory() as td:
            tracker = QuotaTracker(Path(td) / "q.json",
                                   QuotaPolicy(runs_per_month=1))
            rid = tracker.reserve("token", runs=1)
            self.assertFalse(tracker.check("token", runs=1)["allowed"])
            tracker.release(rid)
            self.assertTrue(tracker.check("token", runs=1)["allowed"])
            rid = tracker.reserve("token", runs=1)
            tracker.settle(rid, runs=1, tokens=10, cost_usd=0.01)
            usage = tracker.check("token", runs=0)["usage"]
            self.assertEqual(usage["runs"], 1)
            self.assertEqual(usage["tokens"], 10)

    def test_tokens_are_not_stored_in_plaintext(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "q.json"
            tracker = QuotaTracker(path)
            tracker.consume("super-secret-token", runs=1)
            self.assertNotIn("super-secret-token", path.read_text())
            self.assertIn("tokens", path.read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
