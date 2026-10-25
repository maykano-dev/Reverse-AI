"""Direct cross-reference recovery tests."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.core.disasm import capstone_available  # noqa: E402
from reverseai.core.xrefs import find_xrefs  # noqa: E402

CC = shutil.which("cc") is not None
CS = capstone_available()


@unittest.skipUnless(CC and CS, "cc or capstone unavailable")
class XRefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        src = Path(cls.tmp.name) / "x.c"
        src.write_text(r"""
#include <stdio.h>
int classify(int x) { return x > 2 ? 1 : 0; }
int main(void) { printf("%d\n", classify(3)); return 0; }
""")
        cls.bin = Path(cls.tmp.name) / "x"
        subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(cls.bin)],
                       check=True, capture_output=True)
        cls.xrefs = find_xrefs(str(cls.bin), max_functions=20)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_functions_are_recovered(self):
        self.assertIn("main", self.xrefs.functions)
        self.assertIn("classify", self.xrefs.functions)
        self.assertGreater(self.xrefs.to_dict()["count"], 0)

    def test_main_calls_classify(self):
        callers = self.xrefs.callers_of("classify")
        self.assertTrue(callers)
        self.assertIn("main", [c["function"] for c in callers])

    def test_main_has_callees(self):
        self.assertTrue(self.xrefs.callees_of("main"))

    def test_report_is_serializable(self):
        data = self.xrefs.to_dict()
        self.assertIn("refs", data)
        self.assertIn("functions", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
