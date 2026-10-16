"""Bomb-safe archive extraction tests.

Run: python3 -m unittest tests.test_archive -v
"""

from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.security.archive import (  # noqa: E402
    BombDetected,
    is_archive,
    safe_extract,
)
from reverseai.security.validate import ValidationError  # noqa: E402


class DetectTests(unittest.TestCase):
    def test_zip(self):
        self.assertEqual(is_archive(b"PK\x03\x04rest"), "zip")

    def test_gzip(self):
        self.assertEqual(is_archive(b"\x1f\x8b\x08\x00"), "gzip")

    def test_not_archive(self):
        self.assertIsNone(is_archive(b"\x7fELF...."))


class ZipExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _zip(self, entries):
        p = self.dir / "a.zip"
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            for name, data in entries.items():
                z.writestr(name, data)
        return p

    def test_normal_extract(self):
        p = self._zip({"a.txt": b"hello", "sub/b.txt": b"world"})
        out = self.dir / "out"
        res = safe_extract(p, out)
        self.assertEqual(res.files, 2)
        self.assertEqual((out / "a.txt").read_bytes(), b"hello")

    def test_zip_bomb_blocked(self):
        # Highly compressible payload: 500 MB of zeros -> tiny zip, huge ratio.
        p = self.dir / "bomb.zip"
        with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("big", b"\x00" * (500 * 1024 * 1024))
        with self.assertRaises(BombDetected):
            safe_extract(p, self.dir / "out", max_total=50 * 1024 * 1024)

    def test_traversal_blocked(self):
        p = self.dir / "trav.zip"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("../escape.txt", b"x")
        with self.assertRaises((ValidationError, BombDetected)):
            safe_extract(p, self.dir / "out")

    def test_too_many_files(self):
        entries = {f"f{i}.txt": b"x" for i in range(50)}
        p = self._zip(entries)
        with self.assertRaises(BombDetected):
            safe_extract(p, self.dir / "out", max_files=10)


class TarExtractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_normal_tar(self):
        p = self.dir / "a.tar.gz"
        with tarfile.open(p, "w:gz") as t:
            info = tarfile.TarInfo("hello.txt")
            data = b"hi there"
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        res = safe_extract(p, self.dir / "out")
        self.assertEqual(res.files, 1)
        self.assertEqual((Path(res.dest) / "hello.txt").read_bytes(), b"hi there")


if __name__ == "__main__":
    unittest.main(verbosity=2)
