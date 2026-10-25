"""Benchmark quality: held-out split, metrics, and checkers that can fail."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.job import Job  # noqa: E402
from reverseai.bench.runner import BenchReport, TaskResult  # noqa: E402
from reverseai.bench.tasks import builtin_tasks  # noqa: E402


class BenchmarkContractTests(unittest.TestCase):
    def test_task_ids_are_unique(self):
        tasks = builtin_tasks()
        ids = [t.id for t in tasks]
        self.assertEqual(len(ids), len(set(ids)))

    def test_development_and_heldout_sets_exist(self):
        tasks = builtin_tasks()
        dev = [t for t in tasks if t.split == "dev"]
        holdout = [t for t in tasks if t.split == "holdout"]
        self.assertGreaterEqual(len(tasks), 10)
        self.assertGreaterEqual(len(dev), 5)
        self.assertGreaterEqual(len(holdout), 4)
        self.assertTrue(all(t.split in ("dev", "holdout") for t in tasks))

    def test_every_task_has_a_goal_and_a_checker(self):
        for t in builtin_tasks():
            self.assertTrue(t.goal.strip(), t.id)
            self.assertTrue(t.description.strip(), t.id)
            self.assertTrue(t.category.strip(), t.id)
            self.assertTrue(callable(t.check), t.id)

    def test_checkers_can_fail_on_an_empty_job(self):
        empty = Job(goal="nothing")
        failing = []
        for t in builtin_tasks():
            if t.id == "missing_target":
                continue  # this one is supposed to pass when no artifact exists
            passed, _ = t.check(empty)
            if not passed:
                failing.append(t.id)
        self.assertGreaterEqual(len(failing), 5)

    def test_refusal_tasks_are_marked(self):
        tasks = [t for t in builtin_tasks() if t.expects_refusal]
        self.assertGreaterEqual(len(tasks), 3)
        self.assertTrue(all(t.split == "holdout" for t in tasks))


class MetricsTests(unittest.TestCase):
    def report(self) -> BenchReport:
        rows = [
            TaskResult("a", True, "ok", "completed", 2, 1.0, verified=True,
                       cost_usd=0.1, split="dev"),
            TaskResult("b", False, "wrong", "completed", 3, 2.0, verified=True,
                       false_verification=True, cost_usd=0.2, split="dev"),
            TaskResult("c", True, "ok", "completed", 4, 3.0, verified=True,
                       repair_attempts=2, cost_usd=0.3, split="holdout"),
            TaskResult("d", False, "refused", "completed", 1, 0.5,
                       refused=True, expected_refusal=True, split="holdout"),
        ]
        return BenchReport(total=4, passed=2, results=rows)

    def test_metrics_are_computed(self):
        r = self.report()
        self.assertEqual(r.verified_success, 2)
        self.assertEqual(r.false_verification_rate, 0.25)
        self.assertEqual(r.repair_success_rate, 1.0)
        self.assertEqual(r.refusal_rate, 1.0)
        self.assertAlmostEqual(r.cost_per_verified, 0.3)
        self.assertIn("dev", r.by_split())
        self.assertIn("holdout", r.by_split())

    def test_render_mentions_false_verification(self):
        text = self.report().render()
        self.assertIn("false verification rate", text)
        self.assertIn("FALSE-VERIFY", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
