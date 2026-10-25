"""Verification repair loop and verified-delivery gate tests.

Real compiled fixture, real sandbox. No network or API key. The model is a
deterministic MockProvider. Skips cleanly when cc or the sandbox is unavailable.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent import Agent, Permission, ToolContext  # noqa: E402
from reverseai.agent.evidence import EvidenceLog  # noqa: E402
from reverseai.agent.providers.mock import MockProvider, call, say  # noqa: E402
from reverseai.agent.verify_tools import (  # noqa: E402
    DifferentialTestTool,
    VerifyModificationTool,
)
from reverseai.modify import BytePatch, apply_byte_patches  # noqa: E402
from reverseai.agent.store import JobStore  # noqa: E402
from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402
from reverseai.server.runs import RunManager  # noqa: E402
from reverseai.verify import InputCase, RepairLoop  # noqa: E402

CC = shutil.which("cc") is not None


def _sandbox_ok() -> bool:
    try:
        create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        return True
    except Exception:
        return False


SANDBOX = _sandbox_ok()


def compile_marker(marker: str = "OLD") -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    src = Path(tmp.name) / "p.c"
    src.write_text(f'#include <stdio.h>\nint main(){{puts("{marker}");return 0;}}\n')
    out = Path(tmp.name) / "p"
    subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(out)],
                   check=True, capture_output=True)
    return tmp, out


def patch(binary: Path, workspace: Path, old: bytes = b"OLD",
          new: bytes = b"NEW", name: str = "candidate") -> Path:
    data = binary.read_bytes()
    off = data.find(old)
    if off < 0:
        raise AssertionError(f"{old!r} not found in {binary}")
    out_dir = workspace / "patches"
    out_dir.mkdir(exist_ok=True)
    res = apply_byte_patches(binary, [BytePatch(off, new, expected_original=old)],
                             out_dir, out_name=name + binary.suffix)
    return Path(res.output_path)


def _policy() -> SandboxPolicy:
    return SandboxPolicy(timeout_seconds=3)


def _case(expect=None) -> list[InputCase]:
    return [InputCase("run", [], expect=expect or {
        "stdout": "NEW", "differs": True})]


@unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
class RepairLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.bin = compile_marker("OLD")
        self.work = Path(self.tmp.name) / "work"
        self.work.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_correct_patch_is_verified_on_first_attempt(self):
        good = patch(self.bin, self.work, new=b"NEW", name="good")
        loop = RepairLoop(str(self.bin), str(good), _case(), policy=_policy(),
                          max_attempts=3)
        result = loop.run()
        self.assertTrue(result.verified, result.reason)
        self.assertEqual(len(result.attempts), 1)
        self.assertEqual(result.passed_tests, 1)
        self.assertTrue(result.attempts[0].passed)

    def test_failing_patch_is_repaired(self):
        bad = patch(self.bin, self.work, new=b"BAD", name="bad")
        good = patch(self.bin, self.work, new=b"NEW", name="fixed")
        calls = {"n": 0}

        def repair(_attempt, _n):
            calls["n"] += 1
            return str(good)

        loop = RepairLoop(str(self.bin), str(bad), _case(), policy=_policy(),
                          max_attempts=2, repair_fn=repair)
        result = loop.run()
        self.assertTrue(result.verified, result.reason)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(len(result.attempts), 2)
        self.assertFalse(result.attempts[0].passed)
        self.assertTrue(result.attempts[1].passed)
        self.assertEqual(Path(result.final_path), good)

    def test_still_failing_is_not_verified(self):
        bad = patch(self.bin, self.work, new=b"BAD", name="bad")
        worse = patch(self.work / "patches" / ("bad" + self.bin.suffix), self.work,
                      old=b"BAD", new=b"NO!", name="worse")
        calls = {"n": 0}

        def repair(_attempt, _n):
            calls["n"] += 1
            return str(worse)

        loop = RepairLoop(str(self.bin), str(bad), _case(), policy=_policy(),
                          max_attempts=2, repair_fn=repair)
        result = loop.run()
        self.assertFalse(result.verified)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(len(result.attempts), 2)
        self.assertIn("Not verified", result.reason)
        self.assertEqual(result.passed_tests, 0)

    def test_noop_is_not_a_verified_change(self):
        copy = self.work / "copy"
        shutil.copy2(self.bin, copy)
        loop = RepairLoop(str(self.bin), str(copy),
                          _case({"stdout": "OLD", "same_as_original": True}),
                          policy=_policy(), max_attempts=1)
        result = loop.run()
        self.assertFalse(result.verified)
        self.assertIn("behaved identically", result.reason)


@unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
class VerifyToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.bin = compile_marker("OLD")
        self.work = Path(self.tmp.name) / "work"
        self.work.mkdir()
        self.ctx = ToolContext(
            job_id="test", workspace=str(self.work), target_path=str(self.bin),
            sandbox_policy=_policy(), evidence=EvidenceLog(), goal="prove OLD->NEW",
            extra={"provider": None},
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _set_candidate(self, new: bytes, name: str) -> Path:
        p = patch(self.bin, self.work, new=new, name=name)
        self.ctx.extra["modified_path"] = str(p)
        self.ctx.extra["modified_operation"] = "patch"
        return p

    def test_correct_patch_marks_verified(self):
        self._set_candidate(b"NEW", "good")
        tool = VerifyModificationTool()
        res = tool.run({"expect_stdout": "NEW", "expect_diff": True,
                        "max_attempts": 1, "repair": False}, self.ctx)
        self.assertTrue(res.ok, res.content)
        ver = self.ctx.extra["verification"]
        self.assertTrue(ver["verified"])
        self.assertGreaterEqual(ver["passed_tests"], 1)
        self.assertTrue(self.ctx.extra["delivery"]["allowed"])
        self.assertGreaterEqual(self.ctx.evidence.summary()["verified"], 1)

    def test_breaking_patch_blocks_delivery(self):
        bad = self._set_candidate(b"BAD", "bad")
        tool = VerifyModificationTool()
        res = tool.run({"expect_stdout": "NEW", "expect_diff": True,
                        "max_attempts": 1, "repair": False}, self.ctx)
        self.assertFalse(res.ok)
        ver = self.ctx.extra["verification"]
        self.assertFalse(ver["verified"])
        self.assertEqual(ver["passed_tests"], 0)
        self.assertFalse(self.ctx.extra["delivery"]["allowed"])
        self.assertEqual(self.ctx.evidence.summary()["verified"], 0)
        self.assertEqual(Path(ver["artifact_path"]), bad)

    def test_repair_is_fed_back_to_the_model(self):
        self._set_candidate(b"BAD", "bad")
        data = self.bin.read_bytes()
        off = data.find(b"OLD")
        repair_json = json.dumps({"patches": [{
            "offset": off, "hex": "4e4557", "expect_hex": "4f4c44"}]})
        self.ctx.extra["provider"] = MockProvider([say(repair_json)])
        tool = VerifyModificationTool()
        res = tool.run({"expect_stdout": "NEW", "expect_diff": True,
                        "max_attempts": 2, "repair": True}, self.ctx)
        self.assertTrue(res.ok, res.content)
        ver = self.ctx.extra["verification"]
        self.assertTrue(ver["verified"])
        self.assertEqual(len(ver["attempts"]), 2)
        self.assertGreaterEqual(ver["passed_tests"], 1)

    def test_no_expectation_blocks(self):
        self._set_candidate(b"NEW", "good")
        tool = VerifyModificationTool()
        res = tool.run({"max_attempts": 1, "repair": False}, self.ctx)
        self.assertFalse(res.ok)
        ver = self.ctx.extra["verification"]
        self.assertFalse(ver["verified"])
        self.assertIn("No behavioral expectation", ver["reason"])
        self.assertFalse(self.ctx.extra["delivery"]["allowed"])

    def test_differential_tool_flags_regression_without_verifying(self):
        bad = self._set_candidate(b"BAD", "bad")
        tool = DifferentialTestTool()
        res = tool.run({"cases": [{
            "name": "default", "args": [],
            "expect": {"same_as_original": True},
        }]}, self.ctx)
        self.assertTrue(res.ok, res.content)
        self.assertEqual(res.data["unexpected"], ["default"])
        self.assertNotIn("verification", self.ctx.extra)
        self.assertTrue(Path(bad).exists())


@unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
class DeliveryGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.bin = compile_marker("OLD")
        self.off = self.bin.read_bytes().find(b"OLD")

    def tearDown(self):
        self.tmp.cleanup()

    def _patch_call(self, new_hex="4e4557"):
        return call("apply_byte_patch", {"patches": [{
            "offset": self.off, "hex": new_hex, "expect_hex": "4f4c44"}]})

    def test_unverified_change_is_withheld(self):
        events = []
        script = [self._patch_call(), say("Done, I changed it.")]
        agent = Agent(MockProvider(script), max_permission=Permission.WRITE)
        job = agent.run("Change OLD to NEW and deliver it.",
                        target_path=str(self.bin), on_event=events.append)
        self.assertEqual(job.status, "completed")
        self.assertFalse(job.verification.get("verified"))
        self.assertEqual(job.verification.get("passed_tests", 0), 0)
        self.assertFalse(job.delivery.get("allowed"))
        self.assertIsNone(job.artifact)
        self.assertIsNone(job.artifact_meta.get("path"))
        self.assertEqual(job.evidence.summary()["verified"], 0)
        self.assertIn("did not deliver", job.final_answer)
        self.assertTrue(any(e.get("type") == "delivery_blocked" for e in events))
        # The gate ran the verification tool rather than trusting the model.
        self.assertTrue(any(e.get("name") == "verify_modification"
                            for e in events if e.get("type") == "tool_result"))

    def test_verified_change_is_delivered_with_evidence(self):
        events = []
        script = [
            self._patch_call(),
            call("verify_modification", {
                "expect_stdout": "NEW", "expect_diff": True,
                "max_attempts": 1, "repair": False}),
            say("Verified: the new behavior prints NEW."),
        ]
        agent = Agent(MockProvider(script), max_permission=Permission.WRITE)
        job = agent.run("Change OLD to NEW and prove it.",
                        target_path=str(self.bin), on_event=events.append)
        self.assertEqual(job.status, "completed")
        self.assertTrue(job.verification.get("verified"))
        self.assertGreaterEqual(job.verification.get("passed_tests", 0), 1)
        self.assertTrue(job.delivery.get("allowed"))
        self.assertIsNotNone(job.artifact)
        self.assertTrue(Path(job.artifact_meta["path"]).is_file())
        self.assertGreaterEqual(job.evidence.summary()["verified"], 1)
        self.assertTrue(any(e.get("type") == "verification_attempt" for e in events))
        self.assertFalse(any(e.get("type") == "delivery_blocked" for e in events))


@unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
class ServerDeliveryTests(unittest.TestCase):
    def test_blocked_artifact_is_not_persisted_or_served(self):
        tmp, binpath = compile_marker("OLD")
        try:
            def dynamic_patch(messages):
                path = None
                for m in messages:
                    content = getattr(m, "content", None) or ""
                    mo = re.search(r"path:\s*(\S+)\)", content)
                    if mo:
                        path = mo.group(1)
                if not path:
                    raise AssertionError("target path not found")
                off = Path(path).read_bytes().find(b"OLD")
                return call("apply_byte_patch", {"patches": [{
                    "offset": off, "hex": "4e4557", "expect_hex": "4f4c44"}]})

            provider = MockProvider([dynamic_patch, say("Done.")])
            with tempfile.TemporaryDirectory() as store_dir, \
                    mock.patch("reverseai.server.runs.get_provider",
                               return_value=provider):
                with mock.patch.dict("os.environ", {"REVERSEAI_PROVIDER": "mock"}):
                    rm = RunManager(JobStore(store_dir))
                    sid, cid, err = rm.start({
                        "goal": "Change OLD to NEW and deliver it.",
                        "target": str(binpath),
                    })
                    self.assertIsNone(err)
                    self.assertTrue(rm.get(sid).done.wait(20))
                    rec = rm.store.get(sid)
                    self.assertFalse(rec["delivery"]["allowed"])
                    self.assertIsNone(rec["artifact"])
                    self.assertIsNone(rm.store.artifact_for(sid))
                    self.assertIsNone(rm.artifact_path(cid))
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
