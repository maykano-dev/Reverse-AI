"""Modification + verification tests, including a full patch-and-verify agent run.

Run: python3 -m unittest tests.test_modify -v
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent import Agent, Permission  # noqa: E402
from reverseai.agent.providers.mock import MockProvider, call, say  # noqa: E402
from reverseai.modify import BytePatch, PatchError, apply_byte_patches  # noqa: E402
from reverseai.verify import compare_execution  # noqa: E402


def compile_marker(marker: str = "OLD") -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    src = Path(tmp.name) / "p.c"
    src.write_text(f'#include <stdio.h>\nint main(){{puts("{marker}");return 0;}}\n')
    out = Path(tmp.name) / "p"
    subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(out)],
                   check=True, capture_output=True)
    return tmp, out


def _cc_ok() -> bool:
    try:
        compile_marker().__enter__ if False else None
        tmp, _ = compile_marker()
        tmp.cleanup()
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


class PatchEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Path(self.tmp.name) / "data.bin"
        self.src.write_bytes(b"HELLO-WORLD-1234")
        self.out = Path(self.tmp.name) / "out"
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_patch_copy_leaves_original_untouched(self):
        before = self.src.read_bytes()
        res = apply_byte_patches(self.src, [BytePatch(0, b"J")], self.out)
        self.assertEqual(self.src.read_bytes(), before)  # original intact
        self.assertNotEqual(res.original_sha256, res.modified_sha256)
        self.assertTrue(Path(res.output_path).exists())
        self.assertEqual(Path(res.output_path).read_bytes()[0:1], b"J")

    def test_expected_original_guard(self):
        with self.assertRaises(PatchError):
            apply_byte_patches(self.src, [BytePatch(0, b"J", expected_original=b"X")], self.out)
        # correct expectation passes
        apply_byte_patches(self.src, [BytePatch(0, b"J", expected_original=b"H")], self.out)

    def test_out_of_bounds(self):
        with self.assertRaises(PatchError):
            apply_byte_patches(self.src, [BytePatch(100, b"J")], self.out)

    def test_bytes_changed_count(self):
        res = apply_byte_patches(self.src, [BytePatch(0, b"HELXO")], self.out)  # one diff
        self.assertEqual(res.bytes_changed, 1)


@unittest.skipUnless(_cc_ok(), "cc unavailable")
class VerificationTests(unittest.TestCase):
    def test_behavior_change_detected(self):
        tmp, binpath = compile_marker("OLD")
        try:
            data = binpath.read_bytes()
            off = data.find(b"OLD")
            self.assertGreater(off, 0)
            workdir = Path(tmp.name) / "w"
            workdir.mkdir()
            res = apply_byte_patches(
                binpath, [BytePatch(off, b"NEW", expected_original=b"OLD")], workdir)
            report = compare_execution(str(binpath), res.output_path)
            self.assertTrue(report.ran, report.to_dict())
            self.assertTrue(report.same_exit)        # both exit 0
            self.assertFalse(report.same_stdout)     # OLD vs NEW
            self.assertIn("OLD", report.original.stdout)
            self.assertIn("NEW", report.modified.stdout)
        finally:
            tmp.cleanup()

    def test_identical_copy_identical_behavior(self):
        tmp, binpath = compile_marker("SAME")
        try:
            workdir = Path(tmp.name) / "w"
            workdir.mkdir()
            # no-op patch: write same byte back
            b0 = binpath.read_bytes()[0:1]
            res = apply_byte_patches(binpath, [BytePatch(0, b0)], workdir)
            report = compare_execution(str(binpath), res.output_path)
            self.assertTrue(report.ran)
            self.assertTrue(report.same_exit and report.same_stdout)
            self.assertIn("identical", report.verdict)
        finally:
            tmp.cleanup()


@unittest.skipUnless(_cc_ok(), "cc unavailable")
class FullPatchLoopTests(unittest.TestCase):
    def test_agent_patches_and_verifies(self):
        tmp, binpath = compile_marker("OLD")
        try:
            data = binpath.read_bytes()
            off = data.find(b"OLD")
            script = [
                call("analyze_binary", {}),
                call("apply_byte_patch",
                     {"patches": [{"offset": off, "hex": "4e4557", "expect_hex": "4f4c44"}]}),
                call("verify_modification", {
                    "expect_stdout": "NEW", "expect_diff": True,
                    "max_attempts": 1, "repair": False}),
                say("Verified: patched OLD->NEW; the behavioral test passed."),
            ]
            agent = Agent(MockProvider(script), max_permission=Permission.WRITE)
            job = agent.run("Change the printed message from OLD to NEW and prove it.",
                            target_path=str(binpath))

            self.assertEqual(job.status, "completed")
            # modification tool must be registered only because ceiling is WRITE
            self.assertIn("apply_byte_patch", agent.registry.names())
            self.assertIn("verify_modification", agent.registry.names())
            self.assertTrue(job.verification["verified"])
            self.assertGreaterEqual(job.verification["passed_tests"], 1)
            self.assertTrue(job.delivery["allowed"])
            self.assertIsNotNone(job.artifact)
            # a verified behavioral finding exists
            self.assertGreaterEqual(job.evidence.summary()["verified"], 1)
            tools_called = {e.tool for e in agent.mediator.audit if e.allowed and e.ok}
            self.assertIn("apply_byte_patch", tools_called)
            self.assertIn("verify_modification", tools_called)
        finally:
            tmp.cleanup()

    def test_write_tools_hidden_without_write_ceiling(self):
        agent = Agent(MockProvider([say("x")]), max_permission=Permission.EXECUTE)
        self.assertNotIn("apply_byte_patch", agent.registry.names())


if __name__ == "__main__":
    unittest.main(verbosity=2)
