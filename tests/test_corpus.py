"""Durable behavioral corpus tests.

Real compiled fixture, real sandbox. No network or API key. Skips cleanly when
cc or the isolating sandbox is unavailable.
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
from reverseai.agent.corpus_tools import CaptureBehaviorCorpusTool  # noqa: E402
from reverseai.agent.evidence import EvidenceLog  # noqa: E402
from reverseai.agent.providers.mock import MockProvider, call, say  # noqa: E402
from reverseai.agent.tools import ToolContext  # noqa: E402
from reverseai.agent.verify_tools import VerifyModificationTool  # noqa: E402
from reverseai.modify import BytePatch, apply_byte_patches  # noqa: E402
from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402
from reverseai.verify import InputCase  # noqa: E402
from reverseai.verify.corpus import (  # noqa: E402
    CorpusStore,
    capture_corpus,
    load_for_target,
    target_sha256,
)

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


def patch(binary: Path, workspace: Path, new: bytes = b"NEW",
          name: str = "candidate", also_stable: bool = False) -> Path:
    data = binary.read_bytes()
    off = data.find(b"OLD")
    patches = [BytePatch(off, new, expected_original=b"OLD")]
    if also_stable:
        stable = data.find(b"STABLE")
        patches.append(BytePatch(stable, b"BROKEN", expected_original=b"STABLE"))
    out_dir = workspace / "patches"
    out_dir.mkdir(exist_ok=True)
    return Path(apply_byte_patches(binary, patches, out_dir,
                                   out_name=name + binary.suffix).output_path)


@unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.tmp, self.bin = compile_fixture()
        self.work = Path(self.tmp.name) / "work"
        self.work.mkdir()
        self.store = CorpusStore(Path(self.tmp.name) / "corpora")
        self.ctx = ToolContext(
            job_id="corpus-test", workspace=str(self.work),
            target_path=str(self.bin),
            sandbox_policy=SandboxPolicy(timeout_seconds=3),
            evidence=EvidenceLog(), goal="preserve the default behavior",
            extra={"corpus_store": self.store},
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _capture_keep(self):
        tool = CaptureBehaviorCorpusTool()
        res = tool.run({"cases": [{"name": "keep", "args": ["--keep"]}]}, self.ctx)
        self.assertTrue(res.ok, res.content)
        return res

    def test_capture_persists_original_expectations(self):
        res = self._capture_keep()
        sha = target_sha256(self.bin)
        self.assertEqual(res.data["target_sha256"], sha)
        loaded = self.store.load(sha)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].name, "keep")
        self.assertTrue(loaded[0].expect["same_as_original"])
        self.assertIn("STABLE", loaded[0].expect["stdout"])
        summary = self.store.summary(sha)
        self.assertEqual(summary["cases"], 1)

    def test_capture_direct_and_load_prefix(self):
        cases = [InputCase("keep", ["--keep"])]
        captured, summary = capture_corpus(
            str(self.bin), cases,
            policy=SandboxPolicy(timeout_seconds=3))
        self.assertEqual(len(captured), 1)
        self.assertIn("STABLE", captured[0].expect["stdout"])
        sha = self.store.save(target_sha256(self.bin), captured)
        self.assertTrue(Path(sha).is_file())
        prefixed = load_for_target(self.store, str(self.bin))
        self.assertEqual(prefixed[0].name, "corpus/keep")

    def test_verify_uses_corpus_and_passes_good_change(self):
        self._capture_keep()
        good = patch(self.bin, self.work, new=b"NEW", name="good")
        self.ctx.extra["modified_path"] = str(good)
        self.ctx.extra["modified_operation"] = "patch"
        res = VerifyModificationTool().run({
            "cases": [{"name": "new", "args": ["--new"],
                       "expect": {"stdout": "NEW", "differs": True}}],
            "use_corpus": True,
            "max_attempts": 1, "repair": False,
        }, self.ctx)
        self.assertTrue(res.ok, res.content)
        verification = self.ctx.extra["verification"]
        self.assertTrue(verification["verified"])
        self.assertEqual(verification["corpus_controls"], 1)

    def test_verify_blocks_when_corpus_regresses(self):
        self._capture_keep()
        bad = patch(self.bin, self.work, new=b"NEW", name="bad",
                    also_stable=True)
        self.ctx.extra["modified_path"] = str(bad)
        self.ctx.extra["modified_operation"] = "patch"
        res = VerifyModificationTool().run({
            "cases": [{"name": "new", "args": ["--new"],
                       "expect": {"stdout": "NEW", "differs": True}}],
            "use_corpus": True,
            "max_attempts": 1, "repair": False,
        }, self.ctx)
        self.assertFalse(res.ok)
        verification = self.ctx.extra["verification"]
        self.assertFalse(verification["verified"])
        self.assertIn("corpus/keep",
                      verification["test_summary"]["unexpected"])
        self.assertFalse(self.ctx.extra["delivery"]["allowed"])

    def test_missing_corpus_is_an_honest_failure(self):
        good = patch(self.bin, self.work, new=b"NEW", name="good")
        self.ctx.extra["modified_path"] = str(good)
        res = VerifyModificationTool().run({
            "expect_stdout": "NEW", "expect_diff": True,
            "use_corpus": True, "max_attempts": 1, "repair": False,
        }, self.ctx)
        self.assertFalse(res.ok)
        self.assertIn("No captured behavioral corpus", res.error or res.content)
        self.assertFalse(self.ctx.extra["verification"]["verified"])

    def test_plan_and_modify_uses_corpus(self):
        self._capture_keep()
        script = [
            call("plan_and_modify", {
                "goal": "Patch the OLD message to NEW and preserve everything else.",
                "find": "OLD", "replace": "NEW",
                "cases": [{"name": "new", "args": ["--new"],
                           "expect": {"stdout": "NEW", "differs": True}}],
                "use_corpus": True,
                "max_attempts": 1, "repair": False,
            }),
            say("Done."),
        ]
        agent = Agent(MockProvider(script), max_permission=Permission.WRITE)
        conv = agent.open(target_path=str(self.bin), workspace=str(self.work))
        conv.ctx.extra["corpus_store"] = self.store
        job = conv.run_turn("Patch OLD to NEW and preserve the rest.")
        self.assertTrue(job.verification["verified"])
        self.assertTrue(job.delivery["allowed"])
        self.assertIsNotNone(job.artifact)
        self.assertEqual(job.verification.get("corpus_controls"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
