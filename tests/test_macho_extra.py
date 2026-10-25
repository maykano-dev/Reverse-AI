"""Mach-O dylib dependency parsing."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.core import analyze_bytes  # noqa: E402
from reverseai.core.macho import parse_macho  # noqa: E402


def build_macho_with_dylib() -> bytes:
    name = b"/usr/lib/libSystem.B.dylib\x00"
    raw = 24 + len(name)
    cmdsize = (raw + 7) & ~7
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, 0x01000007, 0x3, 0x2,
                         1, cmdsize, 0, 0)
    cmd = struct.pack("<IIIIII", 0xC, cmdsize, 24, 0, 0x10000, 0x10000)
    return header + cmd + name + (b"\x00" * (cmdsize - raw))


class MachOExtraTests(unittest.TestCase):
    def test_dylib_is_recovered(self):
        info = parse_macho(build_macho_with_dylib())
        self.assertIn("/usr/lib/libSystem.B.dylib", info.dylibs)

    def test_analysis_exposes_macho_extra(self):
        report = analyze_bytes(build_macho_with_dylib(), path="x.macho")
        self.assertEqual(report.macho_extra["dylibs"],
                         ["/usr/lib/libSystem.B.dylib"])
        self.assertIn("/usr/lib/libSystem.B.dylib", report.needed_libraries)


if __name__ == "__main__":
    unittest.main(verbosity=2)
