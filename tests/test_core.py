"""Core analysis tests — stdlib unittest, no third-party deps.

Run from the repo root:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.core import analyze_bytes, analyze_file  # noqa: E402
from reverseai.core.identify import detect_format, shannon_entropy  # noqa: E402
from reverseai.core.models import Arch, BinaryFormat  # noqa: E402
from reverseai.core.strings import extract_strings  # noqa: E402


def build_minimal_pe() -> bytes:
    """Construct a structurally valid PE32+ with one executable section.

    Layout: DOS header (0x40) -> PE sig -> COFF(20) -> optional header(240)
    -> one section header(40) -> section body.
    """
    opt_size = 240  # 112 + 16 data directories * 8

    dos = bytearray(0x40)
    dos[0:2] = b"MZ"
    struct.pack_into("<I", dos, 0x3C, 0x40)  # e_lfanew -> PE header at 0x40

    pe_sig = b"PE\x00\x00"

    coff = struct.pack(
        "<HHIIIHH",
        0x8664,      # machine = AMD64
        1,           # number of sections
        0x12345678,  # timestamp
        0,           # ptr to symbol table
        0,           # number of symbols
        opt_size,    # size of optional header
        0x0022,      # characteristics: EXECUTABLE_IMAGE | LARGE_ADDRESS_AWARE
    )

    opt = bytearray(opt_size)
    struct.pack_into("<H", opt, 0, 0x20B)     # magic = PE32+
    struct.pack_into("<I", opt, 16, 0x1000)   # AddressOfEntryPoint
    struct.pack_into("<H", opt, 68, 3)        # subsystem = windows-cui
    struct.pack_into("<I", opt, 108, 16)      # NumberOfRvaAndSizes
    # data directories (start at 112) left zero -> no import table

    section = struct.pack(
        "<8sIIIIIIHHI",
        b".text\x00\x00\x00",  # name
        0x1000,                # VirtualSize
        0x1000,                # VirtualAddress
        0x200,                 # SizeOfRawData
        0x170,                 # PointerToRawData (0x40+4+20+240+40 = 0x170)
        0, 0, 0, 0,            # relocs/linenumbers
        0x60000020,            # chars: CODE | EXECUTE | READ
    )

    body = b"\x90" * 0x200  # NOP sled for the section body
    return bytes(dos) + pe_sig + coff + bytes(opt) + section + body


class FormatDetectionTests(unittest.TestCase):
    def test_elf_magic(self):
        self.assertIs(detect_format(b"\x7fELF" + b"\x00" * 60), BinaryFormat.ELF)

    def test_macho_magic(self):
        self.assertIs(detect_format(b"\xcf\xfa\xed\xfe" + b"\x00" * 60), BinaryFormat.MACHO)

    def test_pe_requires_signature(self):
        # "MZ" alone is not a PE without a valid PE header pointer.
        self.assertIs(detect_format(b"MZ" + b"\x00" * 100), BinaryFormat.UNKNOWN)

    def test_unknown(self):
        self.assertIs(detect_format(b"not a binary at all"), BinaryFormat.UNKNOWN)

    def test_too_short(self):
        self.assertIs(detect_format(b"MZ"), BinaryFormat.UNKNOWN)


class EntropyTests(unittest.TestCase):
    def test_uniform_bytes_zero_entropy(self):
        self.assertEqual(shannon_entropy(b"\x00" * 1000), 0.0)

    def test_full_range_high_entropy(self):
        data = bytes(range(256)) * 4
        self.assertGreater(shannon_entropy(data), 7.9)

    def test_empty(self):
        self.assertEqual(shannon_entropy(b""), 0.0)


class StringsTests(unittest.TestCase):
    def test_ascii(self):
        data = b"\x00\x01Hello, world!\x00\xff"
        self.assertIn("Hello, world!", extract_strings(data, min_len=4))

    def test_utf16le(self):
        data = "Config".encode("utf-16-le")
        self.assertIn("Config", extract_strings(b"\x00" + data + b"\x00", min_len=4))

    def test_min_len_filters_short(self):
        self.assertEqual(extract_strings(b"ab\x00cd", min_len=4), [])

    def test_limit(self):
        data = (b"word\x00" * 50)
        self.assertEqual(len(extract_strings(data, min_len=4, limit=5)), 5)


class PEAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.report = analyze_bytes(build_minimal_pe(), path="minimal.exe")

    def test_format(self):
        self.assertIs(self.report.fmt, BinaryFormat.PE)

    def test_arch_and_bits(self):
        self.assertIs(self.report.arch, Arch.X86_64)
        self.assertEqual(self.report.bits, 64)

    def test_entry_and_subsystem(self):
        self.assertEqual(self.report.entry_point, 0x1000)
        self.assertEqual(self.report.subsystem, "windows-cui")

    def test_binary_type_exe(self):
        self.assertEqual(self.report.binary_type, "exe")

    def test_section(self):
        self.assertEqual(len(self.report.sections), 1)
        text = self.report.sections[0]
        self.assertEqual(text.name, ".text")
        self.assertIn("x", text.flags)
        self.assertIn("r", text.flags)

    def test_hashes_present(self):
        self.assertEqual(len(self.report.hashes["sha256"]), 64)

    def test_json_roundtrip(self):
        import json

        d = self.report.to_dict()
        json.dumps(d)  # must be serializable
        self.assertEqual(d["fmt"], "pe")
        self.assertEqual(d["arch"], "x86_64")


class ELFAnalysisTests(unittest.TestCase):
    """Compile a real ELF with cc and verify we parse it the same as readelf."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        src = Path(cls.tmp.name) / "hello.c"
        src.write_text('#include <stdio.h>\nint main(){puts("REVERSEAI_MARKER");return 0;}\n')
        cls.bin = Path(cls.tmp.name) / "hello"
        try:
            subprocess.run(
                ["cc", "-no-pie", "-O0", str(src), "-o", str(cls.bin)],
                check=True, capture_output=True,
            )
            cls.compiled = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            cls.compiled = False

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        if not self.compiled:
            self.skipTest("cc not available or compile failed")
        self.report = analyze_file(self.bin)

    def test_format(self):
        self.assertIs(self.report.fmt, BinaryFormat.ELF)

    def test_exe_type(self):
        self.assertEqual(self.report.binary_type, "exe")  # -no-pie => ET_EXEC

    def test_has_text_section(self):
        names = {s.name for s in self.report.sections}
        self.assertIn(".text", names)

    def test_entry_nonzero(self):
        self.assertTrue(self.report.entry_point)

    def test_marker_string(self):
        self.assertIn("REVERSEAI_MARKER", self.report.strings_sample)

    def test_arch_matches_readelf(self):
        out = subprocess.run(
            ["readelf", "-h", str(self.bin)], capture_output=True, text=True
        ).stdout
        if "X86-64" in out or "x86-64" in out:
            self.assertIs(self.report.arch, Arch.X86_64)
        elif "AArch64" in out:
            self.assertIs(self.report.arch, Arch.ARM64)


class ELFDynamicTests(unittest.TestCase):
    """Dynamic imports/needed-libs on a real system binary, cross-checked."""

    def setUp(self):
        from pathlib import Path as _P

        self.bin = "/usr/bin/objdump"
        if not _P(self.bin).exists():
            self.skipTest("objdump not present")
        from reverseai.core import analyze_file as _af

        self.report = _af(self.bin)

    def test_needed_libraries(self):
        self.assertTrue(self.report.needed_libraries)
        self.assertTrue(any("libc" in lib for lib in self.report.needed_libraries))

    def test_imported_symbols(self):
        self.assertGreater(len(self.report.dynamic_symbols), 0)

    def test_needed_matches_readelf(self):
        out = subprocess.run(["readelf", "-d", self.bin],
                             capture_output=True, text=True).stdout
        needed = [ln for ln in out.splitlines() if "NEEDED" in ln]
        # readelf shows one NEEDED line per dependency
        self.assertEqual(len(needed), len(self.report.needed_libraries))


class FunctionRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        src = Path(cls.tmp.name) / "m.c"
        src.write_text("#include <stdio.h>\n"
                       "int helper(int x){return x*2;}\n"
                       "int main(){printf(\"%d\", helper(21));return 0;}\n")
        cls.bin = Path(cls.tmp.name) / "m"
        try:
            subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(cls.bin)],
                           check=True, capture_output=True)
            cls.ok = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            cls.ok = False

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        if not self.ok:
            self.skipTest("cc unavailable")
        from reverseai.core import analyze_file as _af

        self.report = _af(self.bin)

    def test_finds_user_functions(self):
        names = {f["name"] for f in self.report.functions}
        self.assertIn("main", names)
        self.assertIn("helper", names)

    def test_functions_have_addresses(self):
        main = next(f for f in self.report.functions if f["name"] == "main")
        self.assertGreater(main["address"], 0)
        self.assertGreater(main["size"], 0)

    def test_stripped_binary_yields_none_honestly(self):
        if not shutil.which("strip"):
            self.skipTest("strip unavailable")
        from reverseai.core import analyze_file as _af

        sp = Path(self.tmp.name) / "m_stripped"
        shutil.copy(self.bin, sp)
        subprocess.run(["strip", str(sp)], check=True, capture_output=True)
        self.assertEqual(_af(sp).functions, [])


class HeuristicsTests(unittest.TestCase):
    def _report(self, **kw):
        from reverseai.core.models import AnalysisReport, BinaryFormat

        r = AnalysisReport(path="x", size=kw.get("size", 100_000),
                           fmt=kw.get("fmt", BinaryFormat.PE))
        r.entropy = kw.get("entropy", 5.0)
        r.sections = kw.get("sections", [])
        r.imports = kw.get("imports", {})
        return r

    def test_clean_binary_low(self):
        from reverseai.core.heuristics import assess
        from reverseai.core.models import Section

        rep = self._report(
            entropy=5.5,
            sections=[Section(name=".text", flags="rx", entropy=6.0)],
            imports={"KERNEL32.dll": ["CreateFileW", "ReadFile", "WriteFile",
                                      "CloseHandle", "GetLastError", "ExitProcess"]},
        )
        self.assertEqual(assess(rep).packing_likelihood, "low")

    def test_upx_sections_flagged(self):
        from reverseai.core.heuristics import assess
        from reverseai.core.models import Section

        rep = self._report(
            entropy=7.4,
            sections=[Section(name="UPX0", flags="rwx", entropy=7.5),
                      Section(name="UPX1", flags="rx", entropy=7.8)],
            imports={"KERNEL32.dll": ["LoadLibraryA"]},
        )
        a = assess(rep)
        self.assertEqual(a.packing_likelihood, "high")
        self.assertTrue(any("UPX" in s for s in a.signals))

    def test_malware_indicators_injection_and_c2(self):
        from reverseai.core.heuristics import assess

        rep = self._report(imports={"KERNEL32.dll": [
            "VirtualAllocEx", "WriteProcessMemory", "CreateRemoteThread"],
            "WININET.dll": ["InternetOpenA", "InternetOpenUrlA"],
            "ADVAPI32.dll": ["RegSetValueExA"]})
        a = assess(rep)
        self.assertEqual(a.suspicion, "high")  # 3+ categories incl injection+c2
        self.assertTrue(any("process-injection" in i for i in a.indicators))
        self.assertTrue(any("download-c2" in i for i in a.indicators))

    def test_benign_imports_low_suspicion(self):
        from reverseai.core.heuristics import assess

        rep = self._report(imports={"KERNEL32.dll": [
            "CreateFileW", "ReadFile", "WriteFile", "CloseHandle"]})
        self.assertEqual(assess(rep).suspicion, "low")

    def test_elf_dynamic_symbol_indicators(self):
        from reverseai.core.heuristics import assess
        from reverseai.core.models import BinaryFormat

        rep = self._report(fmt=BinaryFormat.ELF)
        rep.dynamic_symbols = ["ptrace", "execve", "gethostbyname"]
        a = assess(rep)
        # execve (code-exec) + gethostbyname (download-c2) -> at least medium
        self.assertIn(a.suspicion, ("medium", "high"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
