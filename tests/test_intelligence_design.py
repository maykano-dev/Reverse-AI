"""Architecture search, algorithm comparison, twins, and forged tools."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.intelligence.design import (  # noqa: E402
    AlgorithmOptimizer, ArchitectureSearch, Candidate, Objective,
    pareto_front, score_candidates,
)
from reverseai.intelligence.forge import ForgeError, ToolForge  # noqa: E402
from reverseai.intelligence.twin import (  # noqa: E402
    Contract, DigitalTwin, SimulationFactory, TwinChange,
)
from reverseai.intelligence.world import WorldModel  # noqa: E402
from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402


def _sandbox_ok() -> bool:
    try:
        create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        return True
    except Exception:
        return False


SANDBOX = _sandbox_ok()


class ArchitectureTests(unittest.TestCase):
    def candidates(self):
        return [
            Candidate("a", "A", measurements={"perf": 9, "cost": 8},
                      risk=3, complexity=3, cost=8),
            Candidate("b", "B", measurements={"perf": 9, "cost": 2},
                      risk=1, complexity=1, cost=2),
            Candidate("c", "C", measurements={"perf": 10, "cost": 9},
                      risk=4, complexity=4, cost=9),
        ]

    def test_weighted_score_and_recommendation(self):
        objs = [Objective("perf", 0.7), Objective("cost", 0.3, "min")]
        report = ArchitectureSearch().search(self.candidates(), objs)
        self.assertTrue(report.recommendation)
        self.assertEqual(len(report.scores), 3)
        self.assertIn(report.confidence, ("observed", "hypothesis"))

    def test_pareto_front_excludes_dominated(self):
        objs = [Objective("perf"), Objective("cost", direction="min")]
        front = pareto_front(self.candidates(), objs)
        self.assertIn("b", front)
        self.assertIn("c", front)
        self.assertNotIn("a", front)

    def test_constraint_violation_removes_candidate(self):
        c = self.candidates()
        c[0].attributes["needs_gpu"] = False
        report = ArchitectureSearch().search(
            c, [Objective("perf")], constraints=["needs_gpu"])
        self.assertNotIn("a", report.scores)
        self.assertTrue(report.recommendation)

    def test_unmeasured_objective_is_named(self):
        report = ArchitectureSearch().search(
            self.candidates(), [Objective("security")])
        self.assertIn("security", report.unmeasured)

    def test_algorithm_comparison_measures_and_checks_equivalence(self):
        def bench(name, case):
            if name == "slow":
                return {"output": case["x"] * 2, "seconds": 0.4}
            return {"output": case["x"] * 2, "seconds": 0.1}
        cmp = AlgorithmOptimizer().compare(
            "slow", "fast", [{"x": 1}, {"x": 2}], bench)
        self.assertTrue(cmp.equivalent)
        self.assertEqual(cmp.speedup, 4.0)
        self.assertEqual(cmp.confidence, "observed")
        self.assertIn("faster", cmp.improvement)

    def test_broken_algorithm_is_not_equivalent(self):
        def bench(name, case):
            return {"output": case["x"] * (2 if name == "slow" else 3),
                    "seconds": 0.1}
        cmp = AlgorithmOptimizer().compare("slow", "fast", [{"x": 2}], bench)
        self.assertFalse(cmp.equivalent)


class TwinTests(unittest.TestCase):
    def world(self):
        wm = WorldModel("service")
        api = wm.add_node("component", "api")
        db = wm.add_node("component", "db")
        wm.add_edge(api.id, db.id, "depends_on")
        return wm, api, db

    def test_contract_failure_is_predicted(self):
        wm, api, db = self.world()
        twin = DigitalTwin(wm)
        twin.add_contract(Contract(db.id, requires=["db"], provides=["query"],
                                   evidence="integration test"))
        sim = twin.simulate(TwinChange(db.id, "remove db", removes=["db"]))
        self.assertTrue(sim.predicted_failures)
        self.assertEqual(sim.predicted_failures[0]["name"], "db")

    def test_unmodeled_components_are_named(self):
        wm, api, db = self.world()
        sim = DigitalTwin(wm).simulate(TwinChange(db.id, "change db"))
        self.assertTrue(sim.unverified)
        self.assertIn("live_test", sim.hybrid_plan)
        self.assertEqual(sim.confidence, "hypothesis")

    def test_simulation_factory_records_assumptions(self):
        wm, _, _ = self.world()
        env = SimulationFactory().from_world(wm)
        self.assertEqual(env.status, "provisional")
        self.assertTrue(env.assumptions)
        self.assertTrue(env.omissions)
        self.assertEqual(env.validated_against, [])


@unittest.skipUnless(SANDBOX, "isolating sandbox unavailable")
class ForgeTests(unittest.TestCase):
    def test_forged_tool_is_tested_in_the_sandbox(self):
        with tempfile.TemporaryDirectory() as td:
            forge = ToolForge(td)
            tool = forge.create(
                "add_one", "add one to x",
                "def run(payload):\n    return {'value': int(payload['x']) + 1}\n")
            tool = forge.test(tool, [{"name": "two", "inputs": {"x": 1},
                                      "expect": {"value": 2}}])
            self.assertEqual(tool.passed, 1, tool.tests)
            self.assertEqual(tool.status, "tested")
            tool = forge.promote(tool)
            self.assertEqual(tool.status, "promoted")
            self.assertEqual(len(forge.list()), 1)

    def test_failing_tool_is_not_promoted(self):
        with tempfile.TemporaryDirectory() as td:
            forge = ToolForge(td)
            tool = forge.create(
                "bad_tool", "wrong",
                "def run(payload):\n    return {'value': 99}\n")
            tool = forge.test(tool, [{"inputs": {}, "expect": {"value": 1}}])
            self.assertEqual(tool.status, "failed")
            with self.assertRaises(ForgeError):
                forge.promote(tool)

    def test_tool_name_is_validated(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ForgeError):
                ToolForge(td).create("../escape", "x", "def run(p): return p\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
