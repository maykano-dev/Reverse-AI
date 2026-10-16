"""End-to-end pipeline test: analyze -> patch -> diff -> verify.

Locks the core product promise as one flow across core/modify/verify/diff.

Run: python3 -m unittest tests.test_integration -v
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.core import analyze_file  # noqa: E402
from reverseai.core.diff import diff_files  # noqa: E402
from reverseai.core.models import BinaryFormat  # noqa: E402
from reverseai.modify import BytePatch, apply_byte_patches  # noqa: E402
from reverseai.verify import compare_execution  # noqa: E402


@unittest.skipUnless(shutil.which("cc"), "cc unavailable")
class PipelineTests(unittest.TestCase):
    def test_full_change_and_prove(self):
        with tempfile.TemporaryDirectory() as d:
            # 1. build a target that prints OLD
            src = Path(d) / "app.c"
            src.write_text('#include <stdio.h>\n'
                           'int feature(){return 1;}\n'
                           'int main(){puts("OLD");return 0;}\n')
            binp = Path(d) / "app"
            subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(binp)],
                           check=True, capture_output=True)

            # 2. analyze: real structural truth
            report = analyze_file(binp)
            self.assertIs(report.fmt, BinaryFormat.ELF)
            fn_names = {f["name"] for f in report.functions}
            self.assertIn("main", fn_names)
            self.assertIn("feature", fn_names)

            # 3. locate OLD and patch -> NEW on a copy (original untouched)
            data = binp.read_bytes()
            off = data.find(b"OLD")
            self.assertGreater(off, 0)
            res = apply_byte_patches(
                binp, [BytePatch(off, b"NEW", expected_original=b"OLD")], d)
            self.assertEqual(binp.read_bytes(), data)  # original intact

            # 4. structural diff: same arch/format, same size, bytes differ
            d_report = diff_files(str(binp), res.output_path)
            self.assertFalse(d_report.identical)
            self.assertTrue(d_report.same_arch and d_report.same_format)
            self.assertEqual(d_report.size_delta, 0)

            # 5. behavioral verification in the sandbox: exit same, output changed
            vr = compare_execution(str(binp), res.output_path)
            self.assertTrue(vr.ran, vr.to_dict())
            self.assertTrue(vr.same_exit)
            self.assertFalse(vr.same_stdout)
            self.assertIn("OLD", vr.original.stdout)
            self.assertIn("NEW", vr.modified.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
