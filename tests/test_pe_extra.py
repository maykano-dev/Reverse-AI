"""Additional PE inventory: rich header, debug directory, TLS callbacks."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.core import analyze_bytes  # noqa: E402
from reverseai.core.pe import parse_pe  # noqa: E402
from reverseai.core.pe_extra import _rich_header, parse_pe_extra  # noqa: E402
from tests.test_core import build_minimal_pe  # noqa: E402


def build_extra_pe() -> bytes:
    data = bytearray(build_minimal_pe())
    opt = 0x40 + 4 + 20          # 0x58
    dd = opt + 112               # 0xC8
    image_base = 0x140000000
    struct.pack_into("<Q", data, opt + 24, image_base)
    # Section body starts at 0x170; RVA 0x1000 maps there.
    # Debug directory at RVA 0x1000, codeview data at 0x1A0.
    struct.pack_into("<II", data, dd + 6 * 8, 0x1000, 28)
    struct.pack_into("<IIHHIIII", data, 0x170, 0, 0, 0, 0, 2, 40,
                     0x1000 + 0x30, 0x1A0)
    data[0x1A0:0x1A4] = b"RSDS"
    data[0x1A4:0x1B4] = bytes(range(16))
    struct.pack_into("<I", data, 0x1B4, 3)
    data[0x1B8:0x1B8 + 8] = b"x.pdb\x00\x00\x00"
    # TLS directory at RVA 0x1100 (file 0x270), callbacks at RVA 0x1120.
    struct.pack_into("<II", data, dd + 9 * 8, 0x1100, 40)
    struct.pack_into("<QQQQ", data, 0x270, 0, 0, 0, image_base + 0x1120)
    struct.pack_into("<QQ", data, 0x290, image_base + 0x1234, 0)
    return bytes(data)


def build_resource_pe() -> bytes:
    data = bytearray(build_minimal_pe())
    opt = 0x40 + 4 + 20
    dd = opt + 112
    # Root directory at RVA 0x1000 -> file 0x170.
    struct.pack_into("<II", data, dd + 2 * 8, 0x1000, 0x80)
    struct.pack_into("<IIHHHH", data, 0x170, 0, 0, 0, 0, 0, 1)
    struct.pack_into("<II", data, 0x180, 16, 0x80000018)  # RT_VERSION -> subdir
    struct.pack_into("<IIHHHH", data, 0x188, 0, 0, 0, 0, 0, 1)
    struct.pack_into("<II", data, 0x198, 1, 0x80000030)  # name -> subdir
    struct.pack_into("<IIHHHH", data, 0x1A0, 0, 0, 0, 0, 0, 1)
    struct.pack_into("<II", data, 0x1B0, 0x409, 0x48)     # language -> leaf
    struct.pack_into("<IIII", data, 0x1B8, 0x1060, 40, 0, 0)
    version = "CompanyName\x00Acme Corp\x00ProductName\x00Demo\x00".encode(
        "utf-16-le")
    data[0x1D0:0x1D0 + len(version)] = version
    return bytes(data)


class PEExtraTests(unittest.TestCase):
    def test_minimal_pe_has_empty_extras_without_crashing(self):
        data = build_minimal_pe()
        info = parse_pe(data)
        extra = parse_pe_extra(data, info)
        self.assertIn("resources", extra)
        self.assertIn("debug", extra)
        self.assertIn("tls", extra)
        self.assertEqual(extra["resources"], [])

    def test_debug_directory_and_pdb(self):
        data = build_extra_pe()
        extra = parse_pe_extra(data, parse_pe(data))
        self.assertTrue(extra["debug"])
        row = extra["debug"][0]
        self.assertEqual(row["type"], 2)
        self.assertEqual(row["age"], 3)
        self.assertEqual(row["pdb"], "x.pdb")

    def test_tls_callbacks(self):
        data = build_extra_pe()
        extra = parse_pe_extra(data, parse_pe(data))
        self.assertEqual(extra["tls"]["callback_count"], 1)
        self.assertEqual(extra["tls"]["callbacks"][0], 0x140001234)

    def test_resource_version_info(self):
        data = build_resource_pe()
        extra = parse_pe_extra(data, parse_pe(data))
        self.assertTrue(extra["resources"])
        self.assertEqual(extra["resources"][0]["type"], 16)
        self.assertTrue(any("Acme" in s for s in extra["version_strings"]))

    def test_rich_header(self):
        key = 0x11223344
        raw = b"\x00" * 4
        raw += struct.pack("<I", 0x536E6144 ^ key)  # DanS
        raw += b"\x00" * 12
        raw += struct.pack("<II", 0x1234 ^ key, 7 ^ key)
        raw += b"Rich" + struct.pack("<I", key)
        rich = _rich_header(raw, len(raw))
        self.assertEqual(rich["key"], f"{key:#x}")
        self.assertTrue(rich["entries"])

    def test_analyze_bytes_includes_extras(self):
        report = analyze_bytes(build_extra_pe(), path="x.exe")
        self.assertIn("debug", report.pe_extra)
        self.assertIn("tls", report.pe_extra)


if __name__ == "__main__":
    unittest.main(verbosity=2)
