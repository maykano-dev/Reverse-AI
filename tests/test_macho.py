"""Mach-O parser tests using a crafted minimal 64-bit Mach-O.

Run: python3 -m unittest tests.test_macho -v
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.core import analyze_bytes  # noqa: E402
from reverseai.core.macho import parse_macho  # noqa: E402
from reverseai.core.models import Arch, BinaryFormat  # noqa: E402


def build_minimal_macho64() -> bytes:
    """x86_64 executable with one LC_SEGMENT_64 containing a __text section."""
    MH_MAGIC_64 = 0xFEEDFACF
    CPU_X86_64 = 0x01000007
    MH_EXECUTE = 0x2
    LC_SEGMENT_64 = 0x19

    # one segment command (72 header bytes) + one section (80 bytes)
    seg_size = 72 + 80
    # 64-bit mach_header is 32 bytes: ...,flags,reserved
    header = struct.pack("<IiiIIIII", MH_MAGIC_64, CPU_X86_64, 0x3, MH_EXECUTE,
                         1, seg_size, 0, 0)

    seg = struct.pack(
        "<II16sQQQQiiII",
        LC_SEGMENT_64, seg_size, b"__TEXT",
        0x100000000, 0x1000,   # vmaddr, vmsize
        0, 0x1000,             # fileoff, filesize
        7, 5,                  # maxprot, initprot
        1, 0,                  # nsects, flags
    )
    sect = struct.pack(
        "<16s16sQQIIIIIIII",
        b"__text", b"__TEXT",
        0x100000000, 0x100,    # addr, size
        0x200,                 # offset
        0, 0, 0, 0, 0, 0, 0,   # align, reloff, nreloc, flags, r1, r2, r3
    )
    blob = header + seg + sect
    blob += b"\x00" * (0x200 - len(blob)) + b"\x90" * 0x100
    return blob


class MachOTests(unittest.TestCase):
    def setUp(self):
        self.blob = build_minimal_macho64()

    def test_detected_as_macho(self):
        report = analyze_bytes(self.blob, "x.macho")
        self.assertIs(report.fmt, BinaryFormat.MACHO)

    def test_arch_and_type(self):
        info = parse_macho(self.blob)
        self.assertIs(info.arch, Arch.X86_64)
        self.assertEqual(info.bits, 64)
        self.assertEqual(info.binary_type, "exe")

    def test_section_recovered(self):
        info = parse_macho(self.blob)
        names = {s.name for s in info.sections}
        self.assertIn("__TEXT,__text", names)

    def test_fat_or_unknown_degrades(self):
        info = parse_macho(b"\xca\xfe\xba\xbe" + b"\x00" * 60)  # fat magic
        self.assertTrue(info.warnings)


if __name__ == "__main__":
    unittest.main(verbosity=2)
