"""Autonomous modification engine tests.

Run: python3 -m unittest tests.test_modify_engine -v

Real compiled fixture, real sandbox, deterministic MockProvider. No network or
API key. Skips cleanly when cc or the isolating sandbox is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent import Agent, Permission  # noqa: E402
from reverseai.agent.evidence import EvidenceLog  # noqa: E402
from reverseai.agent.modify_engine import PlanAndModifyTool  # noqa: E402
from reverseai.agent.providers.mock import MockProvider, call, say  # noqa: E402
from reverseai.agent.tools import ToolContext  # noqa: E402
from reverseai.core import analyze_file  # noqa: E402
from reverseai.modify.planner import build_plan  # noqa: E402
from reverseai.modify.strategy import choose_strategy  # noqa: E402
from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402
from reverseai.verify import build_report, verify_signature  # noqa: E402

CC = shutil.which("cc") is not None


def _sandbox_ok() -> bool:
    try:
        create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        return True
    except Exception:
        return False


SANDBOX = _sandbox_ok()


def compile_fixture() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    src = Path(tmp.name) / "fixture.c"
    src.write_text(r"""
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--new") == 0) puts("OLD");
    else puts("STABLE");
    return 0;
}
""")
    out = Path(tmp.name) / "fixture"
    subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(out)],
                   check=True, capture_output=True)
    return tmp, out


def _cases() -> tuple[list[dict], list[dict]]:
    intended = [{
        "name": "new",
        "args": ["--new"],
        "expect": {"stdout": "NEW", "differs": True},
    }]
    preserve = [{
        "name": "keep",
        "args": ["--keep"],
        "expect": {"stdout": "STABLE"},
    }]
    return intended, preserve


@unittest.skipUnless(CC, "cc unavailable")
class StrategyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.bin = compile_fixture()
        cls.report = analyze_file(cls.bin)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_resource_goal_chooses_resource_edit(self):
        choice = choose_strategy(
            self.report,
            "Change the embedded message text and version label from OLD to NEW.")
        self.assertEqual(choice.strategy, "resource_edit")
        self.assertEqual(choice.mode, "direct")
        self.assertGreater(choice.confidence, 0.3)
        self.assertTrue(choice.rationale)
        self.assertIn("resource", choice.rationale.lower())
        self.assertFalse(choice.needs_clarification)

    def test_logic_goal_chooses_byte_patch(self):
        choice = choose_strategy(
            self.report,
            "Patch the license check so it always passes, without changing anything else.")
        self.assertEqual(choice.strategy, "byte_patch")
        self.assertEqual(choice.mode, "direct")
        self.assertTrue(choice.rationale)
        self.assertIn("logic", choice.rationale.lower())
        self.assertFalse(choice.needs_clarification)

    def test_mode_override_is_respected(self):
        choice = choose_strategy(
            self.report,
            "Reimplement and modernise the program with new capabilities.",
            mode="direct")
        self.assertEqual(choice.mode, "direct")
        self.assertIn(choice.strategy,
                      ("resource_edit", "byte_patch", "component_replace"))
        self.assertEqual(choice.recommended_mode, "modernisation")

    def test_ambiguous_goal_asks_instead_of_guessing(self):
        choice = choose_strategy(self.report, "Make it better.")
        self.assertTrue(choice.needs_clarification)
        self.assertTrue(choice.question)
        self.assertIn("what", choice.question.lower())

    def test_plan_is_ordered_and_scoped(self):
        goal = ("Patch the OLD message to NEW and preserve everything else.")
        choice = choose_strategy(self.report, goal)
        self.assertEqual(choice.strategy, "byte_patch")
        plan = build_plan(self.report, goal, choice)
        self.assertTrue(plan.preserve_rest)
        self.assertEqual([s.id for s in plan.steps],
                         ["investigate", "locate", "impact", "implement", "verify"])
        self.assertTrue(plan.components)
        self.assertIn(plan.blast_radius.level, ("low", "medium", "high"))
        self.assertFalse(plan.needs_clarification)
        self.assertTrue(any("regression inputs" in w for w in plan.warnings))


@unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.bin = compile_fixture()
        self.intended, self.preserve = _cases()

    def tearDown(self):
        self.tmp.cleanup()

    def test_correct_change_is_verified_and_reported(self):
        events = []
        script = [
            call("plan_and_modify", {
                "goal": ("Patch the OLD message to NEW and preserve everything else."),
                "find": "OLD",
                "replace": "NEW",
                "cases": self.intended,
                "preserve_cases": self.preserve,
                "max_attempts": 1,
                "repair": False,
            }),
            say("Done."),
        ]
        agent = Agent(MockProvider(script), max_permission=Permission.WRITE)
        job = agent.run("Patch OLD to NEW and preserve the rest.",
                        target_path=str(self.bin), on_event=events.append)

        self.assertEqual(job.status, "completed")
        self.assertEqual(job.mode, "direct")
        self.assertEqual(job.modification_plan["strategy"], "byte_patch")
        self.assertTrue(job.verification["verified"])
        self.assertGreaterEqual(job.verification["passed_tests"], 2)
        self.assertTrue(job.delivery["allowed"])
        self.assertIsNotNone(job.artifact)
        self.assertTrue(Path(job.artifact_meta["path"]).is_file())
        self.assertGreaterEqual(job.evidence.summary()["verified"], 1)

        plan_events = [e for e in events if e.get("type") == "modification_plan"]
        self.assertTrue(plan_events)
        self.assertEqual(plan_events[0]["plan"]["strategy"], "byte_patch")
        self.assertTrue(any(e.get("type") == "modification_step"
                            and e.get("status") == "done" for e in events))
        self.assertTrue(any(e.get("type") == "verification_attempt" for e in events))

        report = build_report(job.to_dict())
        self.assertTrue(verify_signature(report))
        self.assertEqual(report["artifact"]["sha256"],
                         job.artifact_meta["sha256"])
        self.assertEqual(report["evidence_tier"], "verified")
        self.assertTrue(report["delivery"]["allowed"])
        self.assertGreaterEqual(report["tests_run"], 1)

    def test_unrelated_regression_blocks_delivery(self):
        data = self.bin.read_bytes()
        old = data.find(b"OLD")
        stable = data.find(b"STABLE")
        self.assertGreater(old, 0)
        self.assertGreater(stable, 0)
        events = []
        script = [
            call("plan_and_modify", {
                "goal": ("Patch the OLD message to NEW and preserve everything else."),
                "patches": [
                    {"offset": old, "hex": "4e4557", "expect_hex": "4f4c44"},
                    {"offset": stable, "hex": "42524f4b454e",
                     "expect_hex": "535441424c45"},
                ],
                "cases": self.intended,
                "preserve_cases": self.preserve,
                "max_attempts": 1,
                "repair": False,
            }),
            say("Done."),
        ]
        agent = Agent(MockProvider(script), max_permission=Permission.WRITE)
        job = agent.run("Patch OLD to NEW and preserve the rest.",
                        target_path=str(self.bin), on_event=events.append)

        self.assertFalse(job.verification["verified"])
        self.assertFalse(job.delivery["allowed"])
        self.assertIsNone(job.artifact)
        self.assertIn("unexpected regression", job.verification["reason"])
        self.assertIn("keep", job.verification["test_summary"]["unexpected"])
        self.assertIn("did not deliver", job.final_answer)
        self.assertTrue(any(e.get("type") == "delivery_blocked" for e in events))
        report = build_report(job.to_dict())
        self.assertFalse(report["delivery"]["allowed"])
        self.assertIn("keep", report["differential"]["unexpected"])

    def test_missing_regression_cases_asks_before_changing(self):
        script = [
            call("plan_and_modify", {
                "goal": ("Patch the OLD message to NEW and preserve everything else."),
                "find": "OLD",
                "replace": "NEW",
                "cases": self.intended,
                "max_attempts": 1,
                "repair": False,
            }),
            say("Please provide the regression inputs."),
        ]
        agent = Agent(MockProvider(script), max_permission=Permission.WRITE)
        job = agent.run("Patch OLD to NEW and preserve the rest.",
                        target_path=str(self.bin))
        self.assertIsNone(job.artifact)
        self.assertTrue(job.delivery.get("allowed") is not True)
        # No modification tool ran: the engine asked instead of guessing.
        self.assertNotIn("apply_byte_patch",
                         [e.tool for e in agent.mediator.audit if e.ok])


@unittest.skipUnless(CC, "cc unavailable")
class AmbiguousToolTests(unittest.TestCase):
    def test_plan_and_modify_returns_needs_clarification(self):
        tmp, binp = compile_fixture()
        try:
            ctx = ToolContext(job_id="test", workspace=tmp.name,
                              target_path=str(binp), evidence=EvidenceLog(),
                              goal="Make it better.")
            res = PlanAndModifyTool().run({"goal": "Make it better."}, ctx)
            self.assertFalse(res.ok)
            self.assertEqual(res.error, "needs_clarification")
            self.assertTrue(res.data["needs_clarification"])
            self.assertTrue(res.data["question"])
            self.assertNotIn("modified_path", ctx.extra)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
