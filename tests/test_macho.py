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


def build_macho_with_symbols() -> bytes:
    """64-bit Mach-O with LC_SEGMENT_64 (0 sections) + LC_SYMTAB (2 symbols)."""
    MH_MAGIC_64 = 0xFEEDFACF
    CPU_ARM64 = 0x0100000C  # iOS/Apple-silicon arch
    MH_EXECUTE = 0x2
    LC_SEGMENT_64 = 0x19
    LC_SYMTAB = 0x2

    seg_size = 72  # no sections
    symtab_size = 24
    sizeofcmds = seg_size + symtab_size
    header = struct.pack("<IiiIIIII", MH_MAGIC_64, CPU_ARM64, 0x0, MH_EXECUTE,
                         2, sizeofcmds, 0, 0)
    seg = struct.pack("<II16sQQQQiiII", LC_SEGMENT_64, seg_size, b"__TEXT",
                      0x100000000, 0x1000, 0, 0x1000, 7, 5, 0, 0)

    symoff = 32 + sizeofcmds           # right after load commands
    nsyms = 2
    stroff = symoff + nsyms * 16
    strtab = b"\x00_printf\x00_main\x00"
    symtab_cmd = struct.pack("<IIIIII", LC_SYMTAB, symtab_size,
                             symoff, nsyms, stroff, len(strtab))

    # nlist_64: n_strx(I), n_type(B), n_sect(B), n_desc(H), n_value(Q)
    sym_printf = struct.pack("<IBBHQ", 1, 0x01, 0, 0, 0)            # undefined ext
    sym_main = struct.pack("<IBBHQ", 9, 0x0F, 1, 0, 0x100001000)   # defined ext
    return header + seg + symtab_cmd + sym_printf + sym_main + strtab


def build_fat(slice_bytes: bytes, slice_offset: int = 4096) -> bytes:
    """Wrap a thin Mach-O in a 32-bit fat/universal header (one arm64 slice)."""
    CPU_ARM64 = 0x0100000C
    header = struct.pack(">II", 0xCAFEBABE, 1)  # magic, nfat_arch
    fat_arch = struct.pack(">iIIII", CPU_ARM64, 0x0, slice_offset,
                           len(slice_bytes), 12)
    blob = header + fat_arch
    blob += b"\x00" * (slice_offset - len(blob)) + slice_bytes
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


class MachOSymbolTests(unittest.TestCase):
    def setUp(self):
        self.info = parse_macho(build_macho_with_symbols())

    def test_arm64_arch(self):
        self.assertIs(self.info.arch, Arch.ARM64)

    def test_imported_symbol(self):
        self.assertIn("_printf", self.info.dynamic_symbols)

    def test_defined_function(self):
        names = {f["name"] for f in self.info.functions}
        self.assertIn("_main", names)
        main = next(f for f in self.info.functions if f["name"] == "_main")
        self.assertEqual(main["address"], 0x100001000)

    def test_export(self):
        self.assertIn("_main", self.info.exports)


class MachOFatTests(unittest.TestCase):
    def test_fat_selects_slice_and_parses(self):
        fat = build_fat(build_macho_with_symbols())
        info = parse_macho(fat)
        self.assertTrue(info.is_fat)
        self.assertEqual(info.slice_count, 1)
        self.assertIs(info.arch, Arch.ARM64)
        self.assertIn("_main", {f["name"] for f in info.functions})

    def test_fat_detected_as_macho_by_analyzer(self):
        fat = build_fat(build_macho_with_symbols())
        report = analyze_bytes(fat, "universal.bin")
        self.assertIs(report.fmt, BinaryFormat.MACHO)
        self.assertIn("_main", {f["name"] for f in report.functions})

    def test_java_class_not_mistaken_for_fat(self):
        # Java .class also starts 0xCAFEBABE; absurd nfat_arch must be rejected.
        java = b"\xca\xfe\xba\xbe" + struct.pack(">I", 0x00340000) + b"\x00" * 40
        info = parse_macho(java)
        self.assertTrue(any("Java" in w or "not a Mach-O" in w for w in info.warnings))


if __name__ == "__main__":
    unittest.main(verbosity=2)
