"""LIEF structural-modification tests.

These verify graceful behavior whether or not LIEF is installed. When LIEF is
present they exercise a real add-import/add-section round trip; when absent they
confirm clean degradation (no crashes, honest errors, tools not registered).

Run: python3 -m unittest tests.test_lief_ops -v
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.modify_tools import modification_tools  # noqa: E402
from reverseai.modify.lief_ops import (  # noqa: E402
    LiefUnavailable,
    add_section,
    lief_available,
)

HAVE_LIEF = lief_available()


class AvailabilityTests(unittest.TestCase):
    def test_tools_gated_on_lief(self):
        names = {t.name for t in modification_tools()}
        if HAVE_LIEF:
            self.assertIn("add_imported_library", names)
            self.assertIn("add_section", names)
        else:
            self.assertNotIn("add_imported_library", names)
            self.assertNotIn("add_section", names)

    @unittest.skipIf(HAVE_LIEF, "LIEF installed; absence path not applicable")
    def test_raises_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(LiefUnavailable):
                add_section("/bin/true", d, ".x", b"abc")


@unittest.skipUnless(HAVE_LIEF, "LIEF not installed")
class RoundTripTests(unittest.TestCase):
    def test_add_section_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "h.c"
            src.write_text("int main(){return 0;}\n")
            binp = Path(d) / "h"
            subprocess.run(["cc", "-no-pie", str(src), "-o", str(binp)],
                           check=True, capture_output=True)
            out = add_section(str(binp), d, ".rvai", b"HELLO")
            self.assertTrue(Path(out).exists())
            # the new section should be visible to our own analyzer
            from reverseai.core import analyze_file

            names = {s.name for s in analyze_file(out).sections}
            self.assertIn(".rvai", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
