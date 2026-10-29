"""Boundary tests for the sandbox: network, filesystem, environment, timeout."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402
from reverseai.security.validate import ValidationError, read_target  # noqa: E402


def _sandbox():
    p = SandboxPolicy(allow_untrusted_execution=True, timeout_seconds=2)
    return create_sandbox(p)


class SandboxBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.sb = _sandbox()
        except Exception as exc:  # host has no isolating backend
            raise unittest.SkipTest(f"no isolating sandbox: {exc}")

    def _run(self, code: str, *, timeout: float = 2.0):
        p = SandboxPolicy(allow_untrusted_execution=True, timeout_seconds=timeout)
        return self.sb.run([sys.executable, "-c", code], p)

    def test_network_is_unreachable(self):
        res = self._run(
            "import socket\n"
            "s=socket.socket()\n"
            "s.settimeout(1)\n"
            "try:\n"
            " s.connect(('1.1.1.1',53)); print('CONNECTED')\n"
            "except Exception as e:\n"
            " print('BLOCKED', type(e).__name__)\n", timeout=3)
        self.assertEqual(res.exit_code, 0, res.stderr_text())
        self.assertIn("BLOCKED", res.stdout_text())
        self.assertTrue(res.isolation.network_blocked)

    def test_host_files_are_not_visible(self):
        res = self._run(
            "try:\n"
            " open('/etc/passwd').read(); print('READ')\n"
            "except Exception as e:\n"
            " print('DENIED', type(e).__name__)\n")
        self.assertEqual(res.exit_code, 0, res.stderr_text())
        self.assertIn("DENIED", res.stdout_text())

    def test_environment_is_cleared(self):
        os.environ["REVERSEAI_TEST_SECRET"] = "must-not-leak"
        try:
            res = self._run(
                "import os, json\n"
                "print(json.dumps({k: v for k, v in os.environ.items() "
                "if k in ('HOME', 'REVERSEAI_TEST_SECRET', 'PATH', 'LANG')}))")
        finally:
            os.environ.pop("REVERSEAI_TEST_SECRET", None)
        self.assertEqual(res.exit_code, 0, res.stderr_text())
        self.assertNotIn("must-not-leak", res.stdout_text())
        self.assertNotIn("HOME", res.stdout_text())

    def test_timeout_kills_the_process(self):
        res = self._run("import time; time.sleep(10)", timeout=0.3)
        self.assertTrue(res.timed_out)
        self.assertLess(res.duration_s, 3.0)

    def test_nonzero_exit_is_reported_not_raised(self):
        res = self._run("raise SystemExit(7)")
        self.assertEqual(res.exit_code, 7)
        self.assertFalse(res.ok)

    def test_landlock_is_applied_when_supported(self):
        from reverseai.sandbox import landlock
        if not landlock.available():
            self.skipTest("Landlock unavailable")
        import platform
        if platform.machine().lower() not in ("x86_64", "amd64"):
            self.skipTest("Landlock helper is x86_64-only")
        with tempfile.TemporaryDirectory() as td:
            policy = SandboxPolicy(
                allow_untrusted_execution=True, timeout_seconds=3,
                workdir=td, rw_binds=[td], landlock=True)
            res = self.sb.run([sys.executable, "-c", "print('LANDLOCK')"],
                              policy, cwd=td)
        self.assertEqual(res.exit_code, 0, res.stderr_text())
        self.assertIn("LANDLOCK", res.stdout_text())
        self.assertTrue(res.isolation.landlock)
        self.assertIn("landlock", res.isolation.filesystem)

    def test_workspace_is_writable_and_temporary(self):
        with tempfile.TemporaryDirectory() as td:
            p = SandboxPolicy(allow_untrusted_execution=True, timeout_seconds=2,
                              workdir=td)
            res = self.sb.run([sys.executable, "-c",
                               "open('inside.txt','w').write('x'); print('OK')"],
                              p, cwd=td)
            self.assertEqual(res.exit_code, 0, res.stderr_text())
            self.assertIn("OK", res.stdout_text())
            self.assertFalse(Path("/inside.txt").exists())

    def test_symlink_target_is_refused_by_validation(self):
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "real"
            real.write_bytes(b"x")
            link = Path(td) / "link"
            try:
                link.symlink_to(real)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(ValidationError):
                read_target(link)


if __name__ == "__main__":
    unittest.main(verbosity=2)
