"""Differential testing tests — real compiled fixtures, real sandbox.

Run: python3 -m unittest tests.test_difftest -v
No network, no API key. Skips cleanly when no isolating sandbox or no compiler.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402
from reverseai.verify import (  # noqa: E402
    InputCase,
    generate_corpus,
    run_differential,
)

CC = shutil.which("cc") is not None


def _sandbox_ok() -> bool:
    try:
        create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        return True
    except Exception:
        return False


SANDBOX = _sandbox_ok()


def _compile(tmp: Path, name: str, body: str) -> Path:
    src = tmp / f"{name}.c"
    src.write_text(body)
    out = tmp / name
    subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(out)],
                   check=True, capture_output=True)
    return out


ORIGINAL = r"""
#include <stdio.h>
int main(void) { puts("OLD"); return 0; }
"""

CHANGED = r"""
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--new") == 0) puts("NEW");
    else puts("OLD");
    return 0;
}
"""

BAD = r"""
#include <stdio.h>
int main(int argc, char **argv) {
    (void)argv;
    if (argc > 1) puts("NEW");
    else puts("BAD");
    return 0;
}
"""


@unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
class DifferentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.original = _compile(self.dir, "original", ORIGINAL)
        self.modified = _compile(self.dir, "modified", CHANGED)
        self.bad = _compile(self.dir, "bad", BAD)

    def tearDown(self):
        self.tmp.cleanup()

    def test_expected_delta_only(self):
        cases = [
            InputCase("default", [], expect={"same_as_original": True}),
            InputCase("switch", ["--new"],
                      expect={"stdout": "NEW", "differs": True}),
        ]
        report = run_differential(
            str(self.original), str(self.modified), cases,
            policy=SandboxPolicy(timeout_seconds=3))
        self.assertTrue(report.ran, report.error)
        self.assertEqual(report.matched, ["default"])
        self.assertEqual(report.differed, ["switch"])
        self.assertEqual(report.unexpected, [])
        self.assertEqual(report.failed_expectations, [])
        self.assertTrue(report.expected_delta_met, report.summary)
        self.assertIn("expected delta met", report.summary)

    def test_unexpected_regression_is_flagged(self):
        cases = [
            InputCase("default", [], expect={"same_as_original": True}),
            InputCase("switch", ["--new"],
                      expect={"stdout": "NEW", "differs": True}),
        ]
        report = run_differential(
            str(self.original), str(self.bad), cases,
            policy=SandboxPolicy(timeout_seconds=3))
        self.assertTrue(report.ran, report.error)
        self.assertIn("default", report.unexpected)
        self.assertFalse(report.expected_delta_met)
        self.assertIn("unexpected regression", report.summary)

    def test_output_files_are_compared(self):
        writer = (
            '#include <stdio.h>\nint main(){FILE*f=fopen("out.txt","w");'
            'if(!f)return 2;fputs("%s\\n",f);fclose(f);return 0;}\n')
        a = _compile(self.dir, "writer_a", writer % "A")
        b = _compile(self.dir, "writer_b", writer % "B")
        cases = [InputCase("file", [], expect={
            "differs": True, "output_files": {"out.txt": "B"}})]
        report = run_differential(
            str(a), str(b), cases, output_files=["out.txt"],
            policy=SandboxPolicy(timeout_seconds=3))
        self.assertTrue(report.ran, report.error)
        self.assertTrue(report.expected_delta_met, report.summary)
        snap = report.cases[0].modified.output_files["out.txt"]
        self.assertEqual(snap["text"].strip(), "B")

    def test_generated_corpus_is_bounded(self):
        cases = generate_corpus([["a"], ["b"]])
        self.assertGreaterEqual(len(cases), 5)
        self.assertLessEqual(len(cases), 32)
        self.assertEqual(cases[0].name, "empty")
        self.assertTrue(any(c.name == "help" for c in cases))
        self.assertTrue(all(isinstance(c, InputCase) for c in cases))

    def test_no_sandbox_is_an_honest_failure(self):
        # Ask for a policy the host cannot satisfy only if it cannot satisfy it.
        if SANDBOX:
            self.skipTest("an isolating sandbox exists; refusal path tested elsewhere")
        report = run_differential(str(self.original), str(self.modified),
                                  [InputCase("x")])
        self.assertFalse(report.ran)
        self.assertIn("sandbox", (report.error or "").lower())


class InputCaseTests(unittest.TestCase):
    def test_roundtrip_and_limits(self):
        c = InputCase("x", ["a"], b"hi", {"in.txt": b"data"},
                      {"stdout": "ok"})
        d = c.to_dict()
        c2 = InputCase.from_dict(d)
        self.assertEqual(c2.args, ["a"])
        self.assertEqual(c2.stdin, b"hi")
        self.assertEqual(c2.files["in.txt"], b"data")
        self.assertEqual(c2.expect["stdout"], "ok")

    def test_too_many_args_rejected(self):
        from reverseai.verify import DiffTestError

        with self.assertRaises(DiffTestError):
            InputCase("x", ["a"] * 40).normalized()

    def test_unsafe_file_name_rejected(self):
        from reverseai.verify import DiffTestError

        with self.assertRaises(DiffTestError):
            InputCase("x", files={"../escape.txt": b"x"}).normalized()
        with self.assertRaises(DiffTestError):
            InputCase("x", files={"/etc/passwd": b"x"}).normalized()


if __name__ == "__main__":
    unittest.main(verbosity=2)
