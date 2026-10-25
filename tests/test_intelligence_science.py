"""Hypothesis loops and causal reasoning with explicit uncertainty."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.intelligence.causal import CausalGraph, CausalError  # noqa: E402
from reverseai.intelligence.science import (  # noqa: E402
    ExperimentEngine, compare_prediction, hypothesis_from_opportunity,
)


class ScienceTests(unittest.TestCase):
    def test_supported_hypothesis_updates_evidence(self):
        engine = ExperimentEngine()
        h = engine.hypothesize("the parser rejects UTF-16 input",
                               {"exit_code": 1})
        exp = engine.design(h.id, "encoding", [
            {"name": "utf16", "prediction": {"exit_code": 1},
             "inputs": {"encoding": "utf16"}},
            {"name": "utf8", "prediction": {"exit_code": 0},
             "inputs": {"encoding": "utf8"}},
        ])
        result = engine.run(exp.id, lambda inputs: {
            "exit_code": 1 if inputs["encoding"] == "utf16" else 0})
        self.assertTrue(result.supported)
        self.assertEqual(result.matched, 2)
        self.assertEqual(engine.hypotheses[h.id].status, "supported")
        self.assertEqual(engine.hypotheses[h.id].confidence, "observed")

    def test_refuted_hypothesis_is_not_promoted(self):
        engine = ExperimentEngine()
        h = engine.hypothesize("the bug is in the cache", {"hit": True})
        exp = engine.design(h.id, "cache", [
            {"name": "miss", "prediction": {"hit": True},
             "inputs": {"cache": "off"}},
        ])
        result = engine.run(exp.id, lambda _: {"hit": False})
        self.assertFalse(result.supported)
        self.assertEqual(result.mismatched, 1)
        self.assertEqual(engine.hypotheses[h.id].status, "refuted")
        self.assertTrue(engine.review())

    def test_environment_error_is_not_evidence(self):
        engine = ExperimentEngine()
        h = engine.hypothesize("the runner works", {"ok": True})
        exp = engine.design(h.id, "x", [{"name": "boom", "prediction": {"ok": True}}])
        result = engine.run(exp.id, lambda _: (_ for _ in ()).throw(OSError("sandbox")))
        self.assertEqual(result.errors, 1)
        self.assertFalse(result.supported)
        self.assertEqual(engine.hypotheses[h.id].status, "untested")

    def test_mismatched_keys_are_reported(self):
        ok, notes = compare_prediction({"a": 1, "b": 2}, {"a": 1})
        self.assertFalse(ok)
        self.assertTrue(any("missing" in n for n in notes))

    def test_untested_hypothesis_needs_no_vote(self):
        engine = ExperimentEngine()
        engine.hypothesize("a guess")
        review = engine.review()
        self.assertIn("no experiment has run", " ".join(review[0]["review"]))
        self.assertIn("no falsifiable prediction", " ".join(review[0]["review"]))

    def test_discriminating_case_prefers_distinct_predictions(self):
        engine = ExperimentEngine()
        a = engine.hypothesize("A", {"x": 1})
        b = engine.hypothesize("B", {"x": 2})
        best = engine.discriminating_case([a.id, b.id],
                                          [{"key": "x", "name": "x"},
                                           {"key": None, "name": "unused"}])
        self.assertEqual(best["case"]["name"], "x")
        self.assertEqual(best["score"], 1.0)

    def test_opportunity_to_hypothesis(self):
        h = hypothesis_from_opportunity({
            "title": "unlock the premium feature",
            "predicts": {"premium": True}})
        self.assertTrue(h.predicts["premium"])


class CausalTests(unittest.TestCase):
    def graph(self):
        g = CausalGraph()
        for n in ("load", "latency", "timeout", "error"):
            g.add_node(n)
        g.add_edge("load", "latency", confidence="observed",
                   evidence="traffic experiment")
        g.add_edge("latency", "timeout", confidence="observed",
                   evidence="timeout threshold")
        g.add_edge("timeout", "error", confidence="observed",
                   evidence="integration test")
        g.set_mechanism("latency", lambda v: v["load"] / 10)
        g.set_mechanism("timeout", lambda v: v["latency"] > 5)
        g.set_mechanism("error", lambda v: v["timeout"])
        return g

    def test_intervention_predicts_through_mechanisms(self):
        out = self.graph().intervene("load", 100)
        self.assertTrue(out["values"]["timeout"])
        self.assertTrue(out["values"]["error"])
        self.assertFalse(out["unknown"])

    def test_missing_mechanism_is_unknown(self):
        g = self.graph()
        g.mechanisms.pop("timeout")
        cf = g.counterfactual("load", "error", 100)
        self.assertEqual(cf.status, "unknown")
        self.assertIn("no established mechanism", cf.reason)

    def test_correlation_only_is_not_causal(self):
        g = CausalGraph()
        g.add_node("a")
        g.add_node("b")
        g.add_edge("a", "b", confidence="hypothesis", evidence="same window")
        cf = g.counterfactual("a", "b", 1)
        self.assertEqual(cf.status, "unknown")

    def test_explanation_labels_candidates(self):
        g = self.graph()
        exp = g.explanation("error")
        self.assertEqual(exp["status"], "observed")
        self.assertEqual(exp["candidates"][0]["cause"], "timeout")

    def test_cycle_is_refused_at_topo(self):
        g = CausalGraph()
        g.add_node("a")
        g.add_node("b")
        g.add_edge("a", "b")
        g.add_edge("b", "a")
        with self.assertRaises(CausalError):
            g.topological()

    def test_unknown_target_is_refused(self):
        with self.assertRaises(CausalError):
            self.graph().intervene("nope", 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
