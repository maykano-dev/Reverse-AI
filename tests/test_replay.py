"""Reproducible verification, replay manifests, readiness, and checkpoints."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.checkpoints import CheckpointError, CheckpointStore  # noqa: E402
from reverseai.cli import main  # noqa: E402
from reverseai.core import analyze_file  # noqa: E402
from reverseai.modify import BytePatch, apply_byte_patches  # noqa: E402
from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402
from reverseai.sandbox.readiness import assess_execution  # noqa: E402
from reverseai.verify.difftest import InputCase  # noqa: E402
from reverseai.verify.replay import (  # noqa: E402
    ReplayError, dump_cases, load_cases, replay_record, write_reports,
)
from reverseai.verify.report import verify_signature  # noqa: E402

CC = shutil.which("cc") is not None


def _sandbox_ok() -> bool:
    try:
        create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        return True
    except Exception:
        return False


SANDBOX = _sandbox_ok()


def compile_fixture() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    src = Path(tmp.name) / "fixture.c"
    src.write_text(r"""
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
    if (argc > 1 && strcmp(argv[1], "--new") == 0) puts("OLD");
    else puts("STABLE");
    return 0;
}
""")
    out = Path(tmp.name) / "fixture"
    subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(out)],
                   check=True, capture_output=True)
    return tmp, out


def make_patch(binary: Path, out_dir: Path) -> Path:
    data = binary.read_bytes()
    off = data.find(b"OLD")
    result = apply_byte_patches(
        binary, [BytePatch(off, b"NEW", expected_original=b"OLD")], out_dir,
        out_name="candidate")
    return Path(result.output_path)


class ReplayTests(unittest.TestCase):
    def test_case_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            cases = [InputCase("one", ["a"], b"x", {"in.txt": b"y"},
                               {"stdout": "ok"})]
            path = dump_cases(cases, Path(td) / "cases.json")
            loaded = load_cases(path)
            self.assertEqual(loaded[0].name, "one")
            self.assertEqual(loaded[0].args, ["a"])
            self.assertEqual(loaded[0].stdin, b"x")
            self.assertEqual(loaded[0].files["in.txt"], b"y")

    def test_bad_case_file_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text("{not json")
            with self.assertRaises(ReplayError):
                load_cases(p)

    def test_missing_modified_file_fails_honestly(self):
        with tempfile.TemporaryDirectory() as td:
            record = replay_record(
                "/bin/ls", str(Path(td) / "does-not-exist"),
                [InputCase("smoke", ["--version"])])
            self.assertFalse(record["verification"]["verified"])
            self.assertFalse(record["delivery"]["allowed"])
            self.assertIn("could not run", record["verification"]["reason"])

    @unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
    def test_signed_report_has_a_replay_recipe(self):
        tmp, binary = compile_fixture()
        try:
            modified = make_patch(binary, Path(tmp.name))
            cases = [
                InputCase("new", ["--new"], expect={"stdout": "NEW",
                                                   "differs": True}),
                InputCase("keep", ["--keep"],
                          expect={"stdout": "STABLE", "same_as_original": True}),
            ]
            record = replay_record(str(binary), str(modified), cases,
                                   goal="change OLD to NEW")
            self.assertTrue(record["verification"]["verified"])
            self.assertTrue(record["delivery"]["allowed"])
            out = Path(tmp.name) / "report.json"
            report = write_reports(record, out)
            self.assertTrue(verify_signature(report))
            self.assertIn("python3 -m reverseai verify", report["replay"]["command"])
            self.assertEqual(report["replay"]["case_count"], 2)
            self.assertEqual(report["replay"]["cases"][0]["name"], "new")
            html = Path(tmp.name) / "report.html"
            write_reports(record, html)
            self.assertIn("Replay", html.read_text())
        finally:
            tmp.cleanup()

    @unittest.skipUnless(CC and SANDBOX, "cc or isolating sandbox unavailable")
    def test_cli_verify_and_report_signature(self):
        tmp, binary = compile_fixture()
        try:
            modified = make_patch(binary, Path(tmp.name))
            cases = [InputCase("new", ["--new"],
                               expect={"stdout": "NEW", "differs": True})]
            case_file = dump_cases(cases, Path(tmp.name) / "cases.json")
            report = Path(tmp.name) / "signed.json"
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["verify", "--original", str(binary),
                           "--modified", str(modified),
                           "--cases", str(case_file),
                           "--report", str(report)])
            self.assertEqual(rc, 0, buf.getvalue())
            self.assertTrue(report.is_file())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(["report", "verify", str(report), "--json"])
            self.assertEqual(rc, 0)
            self.assertTrue(json.loads(buf.getvalue())["valid"])
        finally:
            tmp.cleanup()


class ReadinessTests(unittest.TestCase):
    @unittest.skipUnless(CC, "cc unavailable")
    def test_native_elf_is_executable_when_sandbox_exists(self):
        tmp, binary = compile_fixture()
        try:
            result = assess_execution(str(binary))
            self.assertEqual(result.format, "elf")
            self.assertTrue(result.can_analyze)
            if SANDBOX:
                self.assertEqual(result.verdict, "executable")
                self.assertTrue(result.can_verify_natively)
            else:
                self.assertEqual(result.verdict, "analysis_only")
        finally:
            tmp.cleanup()

    def test_foreign_format_is_analysis_only(self):
        # A minimal Mach-O is not executable on Linux.
        from tests.test_macho import build_minimal_macho64

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sample.macho"
            p.write_bytes(build_minimal_macho64())
            result = assess_execution(str(p))
            self.assertFalse(result.can_verify_natively)
            self.assertEqual(result.verdict, "analysis_only")
            self.assertIn("cannot execute natively", result.reason)


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "work"
        self.root.mkdir()
        (self.root / "a.txt").write_text("one\n")
        (self.root / "sub").mkdir()
        (self.root / "sub" / "b.txt").write_text("two\n")
        self.store = CheckpointStore(Path(self.tmp.name) / "cps",
                                     workspace=self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_review_and_restore(self):
        cp = self.store.create("before edit", "test")
        self.assertEqual(len(cp.files), 2)
        (self.root / "a.txt").write_text("changed\n")
        (self.root / "new.txt").write_text("added\n")
        diff = self.store.review(cp.id)
        self.assertIn("a.txt", diff["changed"])
        self.assertIn("new.txt", diff["added"])
        self.assertIn("-one", diff["diff"])
        self.assertIn("+changed", diff["diff"])
        result = self.store.restore(cp.id, overwrite=True)
        self.assertIn("a.txt", result["restored"])
        self.assertEqual((self.root / "a.txt").read_text(), "one\n")

    def test_restore_refuses_overwrite_by_default(self):
        cp = self.store.create("before edit")
        (self.root / "a.txt").write_text("changed\n")
        with self.assertRaises(CheckpointError):
            self.store.restore(cp.id, overwrite=False)

    def test_malicious_archive_member_is_refused(self):
        cp = self.store.create("before edit")
        evil = Path(self.tmp.name) / "evil.tar.gz"
        with tarfile.open(evil, "w:gz") as tar:
            data = b"owned"
            info = tarfile.TarInfo("../escape.txt")
            info.size = len(data)
            import io as _io
            tar.addfile(info, _io.BytesIO(data))
        shutil.copy2(evil, self.store.dir / f"{cp.id}.tar.gz")
        result = self.store.restore(cp.id, overwrite=True)
        self.assertEqual(result["restored"], [])
        self.assertFalse((Path(self.tmp.name) / "escape.txt").exists())

    def test_symlinks_are_not_snapshotted(self):
        try:
            (self.root / "link").symlink_to("/etc/passwd")
        except OSError:
            self.skipTest("symlinks unavailable")
        cp = self.store.create("no links")
        self.assertNotIn("link", [f.path for f in cp.files])


if __name__ == "__main__":
    unittest.main(verbosity=2)
