"""Binary structural diff tests.

Run: python3 -m unittest tests.test_diff -v
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.core.diff import diff_files  # noqa: E402
from reverseai.modify import BytePatch, apply_byte_patches  # noqa: E402


def _cc_ok() -> bool:
    try:
        subprocess.run(["cc", "--version"], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


class DiffTests(unittest.TestCase):
    def test_identical_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.bin"
            p.write_bytes(b"\x7fELF" + b"A" * 1000)
            diff = diff_files(str(p), str(p))
            self.assertTrue(diff.identical)
            self.assertIn("identical", diff.summary)

    @unittest.skipUnless(_cc_ok(), "cc unavailable")
    def test_patched_copy_diff(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "h.c"
            src.write_text('#include <stdio.h>\nint main(){puts("ABCDE");return 0;}\n')
            binp = Path(d) / "h"
            subprocess.run(["cc", "-no-pie", str(src), "-o", str(binp)],
                           check=True, capture_output=True)
            data = binp.read_bytes()
            off = data.find(b"ABCDE")
            res = apply_byte_patches(binp, [BytePatch(off, b"VWXYZ")], Path(d))
            diff = diff_files(str(binp), res.output_path)
            self.assertFalse(diff.identical)
            self.assertTrue(diff.same_format and diff.same_arch)
            self.assertEqual(diff.size_delta, 0)  # same-length patch


if __name__ == "__main__":
    unittest.main(verbosity=2)
