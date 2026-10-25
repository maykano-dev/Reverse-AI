"""Bounded differential fuzzing."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402
from reverseai.verify.difftest import InputCase  # noqa: E402
from reverseai.verify.fuzz import FuzzError, fuzz_differential  # noqa: E402

CC = shutil.which("cc") is not None


def _sandbox_ok() -> bool:
    try:
        create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        return True
    except Exception:
        return False


SANDBOX = _sandbox_ok()


def compile_pair() -> tuple[tempfile.TemporaryDirectory, Path, Path]:
    tmp = tempfile.TemporaryDirectory()
    src_a = Path(tmp.name) / "a.c"
    src_a.write_text(r"""
#include <stdio.h>
int main(void){int c=getchar(); puts(c=='A'?"OK":"BAD"); return 0;}
""")
    src_b = Path(tmp.name) / "b.c"
    src_b.write_text("#include <stdio.h>\nint main(void){puts(\"OK\");return 0;}\n")
    a = Path(tmp.name) / "a"
    b = Path(tmp.name) / "b"
    for src, out in ((src_a, a), (src_b, b)):
        subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(out)],
                       check=True, capture_output=True)
    return tmp, a, b


@unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
class FuzzTests(unittest.TestCase):
    def test_bounded_fuzz_report(self):
        tmp, a, b = compile_pair()
        try:
            report = fuzz_differential(
                str(a), str(b), [InputCase("seed", [], b"A")],
                iterations=8, seed=1)
            self.assertTrue(report.ran, report.error)
            self.assertEqual(report.cases, 8)
            self.assertIsInstance(report.differences, list)
            self.assertIn("fuzz case", report.summary)
        finally:
            tmp.cleanup()

    def test_empty_seeds_are_refused(self):
        with self.assertRaises(FuzzError):
            fuzz_differential("/bin/true", "/bin/true", [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
