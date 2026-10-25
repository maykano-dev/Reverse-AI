"""Mutation testing measures whether the behavioral corpus can detect breakage."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.evidence import EvidenceLog  # noqa: E402
from reverseai.agent.tools import ToolContext  # noqa: E402
from reverseai.agent.verify_tools import AssessTestStrengthTool  # noqa: E402
from reverseai.modify import BytePatch, apply_byte_patches  # noqa: E402
from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402
from reverseai.verify.difftest import InputCase  # noqa: E402
from reverseai.verify.mutation import (  # noqa: E402
    Mutation, MutationError, assess_mutations, generate_string_mutations,
)

CC = shutil.which("cc") is not None


def _sandbox_ok() -> bool:
    try:
        create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        return True
    except Exception:
        return False


SANDBOX = _sandbox_ok()


def fixture() -> tuple[tempfile.TemporaryDirectory, Path, Path, int]:
    tmp = tempfile.TemporaryDirectory()
    src = Path(tmp.name) / "f.c"
    src.write_text(r"""
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--new") == 0) puts("OLD");
    else puts("STABLE");
    return 0;
}
""")
    original = Path(tmp.name) / "orig"
    subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(original)],
                   check=True, capture_output=True)
    data = original.read_bytes()
    off = data.find(b"OLD")
    modified = Path(tmp.name) / "mod"
    apply_byte_patches(original, [BytePatch(off, b"NEW",
                                            expected_original=b"OLD")],
                       tmp.name, out_name="mod")
    return tmp, original, modified, data.find(b"OLD")


@unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
class MutationTests(unittest.TestCase):
    def test_strong_corpus_kills_a_string_mutation(self):
        tmp, original, modified, _ = fixture()
        try:
            data = modified.read_bytes()
            off = data.find(b"NEW")
            mutation = Mutation("new-to-nex", off + 2, "57", "58",
                                "change the final character")
            strong = [InputCase("new", ["--new"],
                                expect={"stdout": "NEW", "differs": True}),
                      InputCase("keep", ["--keep"],
                                expect={"stdout": "STABLE",
                                        "same_as_original": True})]
            report = assess_mutations(str(original), str(modified), strong,
                                      [mutation])
            self.assertEqual(report.killed, 1, report.to_dict())
            self.assertEqual(report.survived, 0)
            self.assertEqual(report.mutation_score, 1.0)
            self.assertIn("keep", report.weak_cases)
        finally:
            tmp.cleanup()

    def test_weak_corpus_does_not_detect_the_mutation(self):
        tmp, original, modified, _ = fixture()
        try:
            off = modified.read_bytes().find(b"NEW") + 2
            mutation = Mutation("new-to-nex", off, "57", "58")
            weak = [InputCase("keep", ["--keep"],
                              expect={"stdout": "STABLE",
                                      "same_as_original": True})]
            report = assess_mutations(str(original), str(modified), weak,
                                      [mutation])
            self.assertEqual(report.killed, 0)
            self.assertEqual(report.survived, 1)
            self.assertEqual(report.mutation_score, 0.0)
        finally:
            tmp.cleanup()

    def test_mutation_does_not_touch_the_candidate(self):
        tmp, original, modified, _ = fixture()
        try:
            before = hashlib.sha256(modified.read_bytes()).hexdigest()
            off = modified.read_bytes().find(b"NEW") + 2
            mutation = Mutation("one", off, "57", "58")
            assess_mutations(str(original), str(modified),
                             [InputCase("new", ["--new"],
                                        expect={"stdout": "NEW"})], [mutation])
            after = hashlib.sha256(modified.read_bytes()).hexdigest()
            self.assertEqual(before, after)
        finally:
            tmp.cleanup()

    def test_invalid_mutation_is_refused(self):
        tmp, original, modified, _ = fixture()
        try:
            with self.assertRaises(MutationError):
                assess_mutations(str(original), str(modified),
                                 [InputCase("new", ["--new"])],
                                 [Mutation("bad", 10**9, "00", "01")])
        finally:
            tmp.cleanup()

    def test_tool_reports_strength_without_authorizing_delivery(self):
        tmp, original, modified, _ = fixture()
        try:
            ctx = ToolContext(
                job_id="mut", workspace=tmp.name, target_path=str(original),
                sandbox_policy=SandboxPolicy(allow_untrusted_execution=True),
                evidence=EvidenceLog(), goal="test strength",
                extra={"modified_path": str(modified)})
            cases = [{"name": "new", "args": ["--new"],
                      "expect": {"stdout": "NEW", "differs": True}}]
            result = AssessTestStrengthTool().run({"cases": cases}, ctx)
            self.assertTrue(result.ok, result.content)
            self.assertIn("mutation_score", result.data)
            self.assertEqual(result.data["killed"], result.data["total"])
            self.assertNotIn("delivery", ctx.extra)
        finally:
            tmp.cleanup()

    def test_generate_string_mutations(self):
        tmp, original, modified, _ = fixture()
        try:
            mutations = generate_string_mutations(str(original), str(modified),
                                                  ["NEW", "STABLE"])
            self.assertTrue(mutations)
            self.assertTrue(all(m.offset > 0 for m in mutations))
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
