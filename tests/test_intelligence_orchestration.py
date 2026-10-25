"""Model routing, protocol, capability measurement, missions, and learning."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.builtins import default_tools  # noqa: E402
from reverseai.agent.tools import Permission, Tool, ToolContext, ToolResult  # noqa: E402
from reverseai.intelligence.modes import (  # noqa: E402
    MODES, mode_for_strategy, mode_prompt, normalize_mode,
)
from reverseai.intelligence.learning import (  # noqa: E402
    CandidateConfig, EvidenceReconstructor, FailureClassifier,
    GeneralizationEngine, IntelligenceFoundry, KnowledgeTranslator,
    RepresentationSearch, ResearchProgram, SkillLearner,
)
from reverseai.intelligence.orchestration import (  # noqa: E402
    AutonomousEconomy, Budget, CapabilityMap, HumanEscalation,
    IntelligenceCompressor, InvestigationOption, MissionPlanner, ModelProfile,
    ModelRouter, ToolManifest, TrustEngine, export_manifests,
    validate_manifest,
)
from reverseai.intelligence.science import RealityEngine  # noqa: E402
from reverseai.intelligence.world import WorldModel  # noqa: E402


class RouterTests(unittest.TestCase):
    def profiles(self):
        return [
            ModelProfile("cheap", "p", "small", ["code"], 0.1, 500, 16000,
                         success_rate=0.6, samples=20),
            ModelProfile("strong", "p", "large", ["reason", "code"], 5.0, 2000,
                         64000, success_rate=0.9, samples=30),
            ModelProfile("local", "local", "tiny", ["classify"], 0.0, 100,
                         8000, local=True, privacy="local", success_rate=0.7,
                         samples=40),
        ]

    def test_router_requires_capabilities(self):
        decision = ModelRouter(self.profiles()).select(
            "reason", required=["reason"])
        self.assertEqual(decision.profile.name, "strong")
        self.assertTrue(decision.rationale)

    def test_privacy_forces_local(self):
        decision = ModelRouter(self.profiles()).select(
            "classify", privacy="local")
        self.assertEqual(decision.profile.name, "local")

    def test_constraints_can_reject_everything(self):
        decision = ModelRouter(self.profiles()).select(
            "reason", required=["reason"], max_cost=0.01, max_latency=100)
        self.assertIsNone(decision.profile)
        self.assertIn("No model", decision.rationale)

    def test_no_profile_agreement_claim(self):
        decision = ModelRouter(self.profiles()).select("code")
        self.assertTrue(decision.needs_independent_evidence)


class ProtocolTests(unittest.TestCase):
    def test_manifests_cover_permissions_and_boundaries(self):
        manifests = export_manifests(default_tools()[:4])
        self.assertEqual(len(manifests), 4)
        for m in manifests:
            self.assertEqual(validate_manifest(m), [])
            self.assertIn(m["permission"], ("read", "execute", "write", "dangerous"))
            self.assertTrue(m["security_boundary"])

    def test_invalid_manifest_is_reported(self):
        problems = validate_manifest({"name": "x", "permission": "root",
                                      "parameters": []})
        self.assertTrue(problems)

    def test_tool_manifest_from_tool(self):
        tool = default_tools()[0]
        m = ToolManifest.from_tool(tool)
        self.assertEqual(m.name, tool.name)
        self.assertEqual(m.permission, tool.permission.label)


class CapabilityTests(unittest.TestCase):
    def test_small_samples_do_not_publish_a_percentage(self):
        cmap = CapabilityMap(min_samples=5)
        cmap.record("elf_patch", verified=True)
        summary = cmap.summary()
        self.assertFalse(summary["published"])
        self.assertIsNone(summary["verified_rate"])

    def test_failure_modes_and_weakest(self):
        cmap = CapabilityMap(min_samples=2)
        for _ in range(2):
            cmap.record("obfuscated", verified=False,
                        failure_mode="packed")
        for _ in range(3):
            cmap.record("plain", verified=True)
        summary = cmap.summary()
        self.assertTrue(summary["published"])
        self.assertEqual(summary["weakest"][0]["task_class"], "obfuscated")
        self.assertEqual(summary["weakest"][0]["failures"]["packed"], 2)


class MissionTests(unittest.TestCase):
    def test_plan_has_gates_and_acceptance(self):
        mission = MissionPlanner().plan(
            "modernise the service", acceptance=["all tests pass"],
            constraints=["no downtime"], budget_usd=100, deadline_s=3600)
        self.assertEqual(mission.status, "planned")
        self.assertIn("verify", [p["id"] for p in mission.phases])
        self.assertIn("deliver", mission.approvals)
        self.assertEqual(mission.budget_usd, 100)

    def test_budget_and_economy_stop(self):
        budget = Budget(limit_usd=1.0)
        options = [InvestigationOption("cheap", 0.05, 2, 0.5),
                   InvestigationOption("expensive", 5.0, 10, 10)]
        out = AutonomousEconomy().choose(options, budget)
        self.assertEqual(out["choice"]["name"], "cheap")
        self.assertFalse(budget.can_afford(2.0))

    def test_trust_tiers(self):
        trust = TrustEngine()
        self.assertEqual(trust.classify("read a file").tier, "auto")
        self.assertEqual(trust.classify("deploy", reversible=False,
                                        blast_radius="production").tier, "forbid")
        self.assertTrue(trust.classify("change a local copy", reversible=False,
                                       blast_radius="local").approval_required)


class ModeTests(unittest.TestCase):
    def test_five_modes_have_prompts(self):
        self.assertEqual(len(MODES), 5)
        for mode in MODES:
            self.assertTrue(mode_prompt(mode))
            self.assertEqual(normalize_mode(mode), mode)

    def test_strategy_maps_to_a_product_mode(self):
        self.assertEqual(mode_for_strategy("byte_patch"), "modify")
        self.assertEqual(mode_for_strategy("rebuild"), "build")
        self.assertEqual(normalize_mode("direct"), "")


class LearningTests(unittest.TestCase):
    def test_skill_validation_and_staleness(self):
        learner = SkillLearner()
        skill = learner.record("add one", ["read", "add", "test"])
        skill = learner.validate(skill, [
            {"name": "one", "inputs": {"x": 1}, "expect": {"v": 2}}],
            lambda p: {"v": p["x"] + 1})
        self.assertEqual(skill.status, "tested")
        skill = learner.promote(skill)
        self.assertEqual(skill.status, "promoted")
        learner.mark_stale(skill, "API changed")
        self.assertEqual(skill.status, "stale")

    def test_foundry_rejects_holdout_failure(self):
        base = CandidateConfig("base", metrics={"accuracy": 0.5})
        good = CandidateConfig("good", metrics={"accuracy": 0.7},
                               passed_holdout=True)
        bad = CandidateConfig("bad", metrics={"accuracy": 0.99},
                              passed_holdout=False)
        report = IntelligenceFoundry().run(base, [good, bad], holdout_cases=10)
        self.assertEqual(report.winner, "good")
        self.assertTrue(any("bad" in x for x in report.disqualified))

    def test_foundry_keeps_baseline_if_no_candidate_wins(self):
        base = CandidateConfig("base", metrics={"accuracy": 0.9})
        worse = CandidateConfig("worse", metrics={"accuracy": 0.8},
                                passed_holdout=True)
        report = IntelligenceFoundry().run(base, [worse], holdout_cases=5)
        self.assertEqual(report.winner, "base")
        self.assertIn("do not deploy", report.reason)

    def test_analogy_is_a_hypothesis(self):
        a = WorldModel("a")
        a.add_node("component", "db")
        b = WorldModel("b")
        b.add_node("service", "cache")
        analogy = KnowledgeTranslator().compare(a, b)
        self.assertEqual(analogy.status, "hypothesis")
        self.assertTrue(analogy.assumptions)

    def test_failure_classifier(self):
        fc = FailureClassifier()
        self.assertEqual(fc.classify("sandbox unavailable").category, "tool")
        self.assertEqual(fc.classify("timeout after budget").category, "compute")
        self.assertEqual(fc.classify("assertion mismatch").category, "assumption")

    def test_research_program_reports_limits(self):
        report = ResearchProgram().report(
            "why does it fail?", ["a", "b"], [{"case": 1}], [], "a")
        self.assertEqual(report.status, "observed")
        self.assertTrue(report.limitations)

    def test_generalization_catches_holdout_failure(self):
        train = [{"name": "a", "inputs": {"x": 1}, "expect": 2}]
        holdout = [{"name": "b", "inputs": {"x": 3}, "expect": 6}]
        report = GeneralizationEngine().evaluate(
            train, holdout, lambda p: p["x"] * 2)
        self.assertFalse(report.overfit_suspected)
        self.assertIn("survived", report.verdict)
        overfit = GeneralizationEngine().evaluate(
            train, holdout, lambda p: 2 if p["x"] == 1 else 0)
        self.assertTrue(overfit.overfit_suspected)
        self.assertIn("memorize", overfit.verdict)

    def test_representation_search_benchmarks(self):
        out = RepresentationSearch().choose(
            [{"name": "graph"}, {"name": "table"}],
            lambda name: {"score": 2 if name == "graph" else 1})
        self.assertEqual(out["choice"], "graph")

    def test_reconstruction_names_underdetermination(self):
        plan = EvidenceReconstructor().plan(
            {"executable": "app", "behavior_examples": [{"x": 1}],
             "logs": "run.log"})
        self.assertIn("observable behavior and structure", plan.can_reconstruct)
        self.assertTrue(plan.underdetermined)
        self.assertTrue(plan.missing_evidence)
        self.assertEqual(plan.confidence, "observed")

    def test_human_escalation_names_the_decision(self):
        d = HumanEscalation().identify(physical=True, authorization=True,
                                       question="Allow the robot to move?")
        self.assertIsNotNone(d)
        self.assertIn("physical", d.why_human)
        self.assertFalse(d.can_continue)
        self.assertIsNone(HumanEscalation().identify())

    def test_compression_keeps_a_quality_floor(self):
        plan = IntelligenceCompressor().plan("rename a symbol")
        self.assertEqual(plan["stages"][0]["tier"], "deterministic")
        self.assertIn("quality", plan["rule"])
        high = IntelligenceCompressor().plan("deploy", risk="high",
                                             needs_reasoning=True)
        self.assertIn("human", [s["tier"] for s in high["stages"]])

    def test_reality_engine_keeps_classes_distinct(self):
        engine = RealityEngine()
        engine.add("the patch improves speed", "prediction")
        engine.add("simulated 2x", "simulation")
        engine.add("measured 1.8x", "observation")
        self.assertEqual(engine.summary()["strongest"], "observation")
        self.assertEqual(engine.summary()["counts"]["unknown"], 0)
        with self.assertRaises(ValueError):
            engine.add("bad", "vibes")


if __name__ == "__main__":
    unittest.main(verbosity=2)
