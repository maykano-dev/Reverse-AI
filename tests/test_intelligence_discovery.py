"""Autonomous discovery: evidence-backed opportunities and missions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.core.models import AnalysisReport, Arch, BinaryFormat, Section  # noqa: E402
from reverseai.intelligence.discovery import DiscoveryEngine  # noqa: E402
from reverseai.intelligence.world import WorldModel, world_from_analysis  # noqa: E402


def rich_report() -> AnalysisReport:
    return AnalysisReport(
        path="app.bin", size=50000, fmt=BinaryFormat.ELF, arch=Arch.X86_64,
        bits=64, entry_point=0x401000,
        sections=[Section(".text", 0x401000, 0x4000, 0x4000, 0x1000, 6.2, "rx"),
                  Section(".data", 0x405000, 0x2000, 0x2000, 0x5000, 7.8, "rw")],
        imports={f"lib{i}.so": [f"sym_{i}_{j}" for j in range(20)]
                 for i in range(12)},
        exports=[], functions=[{"name": "debug_menu", "address": 0x401000,
                                "size": 40},
                               {"name": "normal_path", "address": 0x401100,
                                "size": 20}],
        strings_sample=["https://api.example.test/v1", "license_key",
                        "feature_flag", "system", "debug"],
        string_count=5, dynamic_symbols=["system", "dlopen"])


class DiscoveryTests(unittest.TestCase):
    def test_finds_hidden_features_and_unlockables(self):
        engine = DiscoveryEngine()
        opps = engine.discover(rich_report())
        categories = {o.category for o in opps}
        self.assertIn("hidden_feature", categories)
        self.assertIn("unlockable_capability", categories)
        self.assertIn("undocumented_api", categories)
        self.assertIn("architecture", categories)
        self.assertTrue(any("debug" in str(o.evidence).lower() for o in opps))

    def test_every_opportunity_has_evidence_and_a_next_step(self):
        engine = DiscoveryEngine()
        for opp in engine.discover(rich_report()):
            self.assertTrue(opp.evidence, opp.title)
            self.assertTrue(opp.proposed_action, opp.title)
            self.assertTrue(0 <= opp.score <= 10)
            self.assertIn(opp.confidence, ("observed", "hypothesis"))

    def test_ranking_is_deterministic(self):
        engine = DiscoveryEngine()
        a = engine.discover(rich_report())
        scores = [o.score for o in a]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_missing_tests_and_corpus_are_opportunities(self):
        engine = DiscoveryEngine()
        opps = engine.discover(rich_report(), corpus_present=False,
                               tests_present=False)
        titles = " ".join(o.title for o in opps).lower()
        self.assertIn("corpus", titles)
        self.assertIn("acceptance", titles)

    def test_mission_respects_effort_budget(self):
        engine = DiscoveryEngine()
        engine.discover(rich_report())
        plan = engine.mission(max_steps=4, max_effort=6)
        self.assertLessEqual(plan["effort_spent"], 6)
        self.assertLessEqual(plan["steps"], 4)
        self.assertTrue(plan["stop_condition"])

    def test_world_model_weak_components_become_an_opportunity(self):
        report = rich_report()
        wm = world_from_analysis(report)
        wm.add_node("component", "guess", confidence="hypothesis")
        engine = DiscoveryEngine(wm)
        opps = engine.discover(report)
        self.assertTrue(any("hypothesis-level" in o.title for o in opps))

    def test_hypotheses_are_falsifiable(self):
        engine = DiscoveryEngine()
        engine.discover(rich_report())
        hyps = engine.hypotheses()
        self.assertTrue(hyps)
        self.assertTrue(all(h.predicts for h in hyps))
        self.assertTrue(all(h.status == "untested" for h in hyps))

    def test_no_opportunities_for_empty_report_are_invented(self):
        report = AnalysisReport(path="empty", size=0, fmt=BinaryFormat.UNKNOWN,
                                arch=Arch.UNKNOWN)
        engine = DiscoveryEngine()
        opps = engine.discover(report, corpus_present=True, tests_present=True)
        # No functions/files means no symbol or architecture claims; the only
        # legitimate output is the missing-test or stripped-symbol signal.
        for o in opps:
            self.assertNotEqual(o.category, "hidden_feature")


if __name__ == "__main__":
    unittest.main(verbosity=2)
