"""APK analysis tests — synthetic APK containing a real ELF native lib.

Run: python3 -m unittest tests.test_apk -v
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.mobile import analyze_apk, is_apk  # noqa: E402

CC = shutil.which("cc") is not None


def _make_so(tmp: Path) -> bytes:
    src = tmp / "n.c"
    src.write_text("int add(int a,int b){return a+b;}\n")
    out = tmp / "libnative.so"
    subprocess.run(["cc", "-shared", "-fPIC", str(src), "-o", str(out)],
                   check=True, capture_output=True)
    return out.read_bytes()


def build_apk(path: Path, so_bytes: bytes | None):
    with zipfile.ZipFile(path, "w") as z:
        # minimal binary-ish manifest string pool with package + permissions
        z.writestr("AndroidManifest.xml",
                   b"\x00com.johndoe.mall\x00android.permission.INTERNET\x00"
                   b"android.permission.CAMERA\x00")
        z.writestr("classes.dex", b"dex\n035\x00" + b"\x00" * 64)
        z.writestr("resources.arsc", b"\x00" * 32)
        z.writestr("res/layout/main.xml", b"<x/>")
        z.writestr("assets/config.json", b"{}")
        if so_bytes:
            z.writestr("lib/arm64-v8a/libnative.so", so_bytes)
            z.writestr("lib/armeabi-v7a/libnative.so", so_bytes)


class APKTests(unittest.TestCase):
    def test_is_apk(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "app.apk"
            build_apk(p, None)
            self.assertTrue(is_apk(str(p)))

    def test_not_apk(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.zip"
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("a.txt", b"hi")
            self.assertFalse(is_apk(str(p)))

    def test_structure(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "app.apk"
            build_apk(p, None)
            rep = analyze_apk(str(p))
            self.assertTrue(rep.is_apk)
            self.assertEqual(rep.package, "com.johndoe.mall")
            self.assertIn("android.permission.INTERNET", rep.permissions)
            self.assertIn("android.permission.CAMERA", rep.permissions)
            self.assertEqual(len(rep.dex_files), 1)

    @unittest.skipUnless(CC, "cc unavailable")
    def test_native_libs_analyzed_as_elf(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            so = _make_so(tmp)
            p = tmp / "app.apk"
            build_apk(p, so)
            rep = analyze_apk(str(p))
            self.assertIn("arm64-v8a", rep.abis)
            self.assertTrue(rep.native_libs)
            # our ELF parser identified the host-arch .so
            self.assertTrue(all(lib.arch != "unknown" for lib in rep.native_libs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
