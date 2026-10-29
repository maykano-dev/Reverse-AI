"""Sandbox tests — exercise real backends on this host.

Run: python3 -m unittest tests.test_sandbox -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.sandbox import (  # noqa: E402
    SandboxPolicy,
    SandboxUnavailable,
    create_sandbox,
    detect_capabilities,
)
from reverseai.sandbox.backends.bubblewrap import BubblewrapSandbox  # noqa: E402
from reverseai.sandbox.backends.subprocess_backend import SubprocessSandbox  # noqa: E402


class DetectTests(unittest.TestCase):
    def test_detect_runs(self):
        caps = detect_capabilities()
        self.assertIsInstance(caps.to_dict(), dict)
        self.assertIn("bubblewrap", caps.to_dict())


class SubprocessBackendTests(unittest.TestCase):
    def setUp(self):
        if not SubprocessSandbox.is_available():
            self.skipTest("non-posix")
        self.sb = SubprocessSandbox()

    def test_echo(self):
        res = self.sb.run(["/bin/echo", "hello"], SandboxPolicy())
        self.assertTrue(res.ok, res.to_dict())
        self.assertEqual(res.stdout_text().strip(), "hello")
        self.assertTrue(res.isolation.resource_limited)

    def test_nonzero_exit(self):
        res = self.sb.run(["/bin/false"], SandboxPolicy())
        self.assertEqual(res.exit_code, 1)
        self.assertFalse(res.ok)

    def test_timeout_is_reported_not_raised(self):
        policy = SandboxPolicy(timeout_seconds=0.5)
        res = self.sb.run(["/bin/sleep", "5"], policy)
        self.assertTrue(res.timed_out)
        self.assertFalse(res.ok)

    def test_minimal_env(self):
        # Host env must not leak in; only policy.env is present.
        res = self.sb.run(["/usr/bin/env"], SandboxPolicy())
        self.assertNotIn("SECRET", res.stdout_text())
        self.assertIn("PATH=", res.stdout_text())

    def test_output_bounded(self):
        policy = SandboxPolicy(max_output_bytes=100)
        res = self.sb.run(["/bin/cat", "/etc/hostname"], policy)
        self.assertLessEqual(len(res.stdout), 100)

    def test_stdin_is_forwarded(self):
        res = self.sb.run(["/bin/cat"], SandboxPolicy(), stdin=b"hello stdin\n")
        self.assertEqual(res.exit_code, 0, res.to_dict())
        self.assertEqual(res.stdout_text(), "hello stdin\n")


@unittest.skipUnless(BubblewrapSandbox.is_available(), "bubblewrap/userns not available")
class BubblewrapBackendTests(unittest.TestCase):
    def setUp(self):
        self.sb = BubblewrapSandbox()

    def test_echo_isolated(self):
        res = self.sb.run(["/bin/echo", "contained"], SandboxPolicy(landlock=False))
        self.assertTrue(res.ok, res.to_dict())
        self.assertEqual(res.stdout_text().strip(), "contained")
        self.assertEqual(res.isolation.filesystem, "namespaced")
        self.assertTrue(res.isolation.pid_namespace)

    def test_network_blocked_by_default(self):
        # With no network namespace interface, a socket connect must fail.
        code = (
            "import socket,sys;"
            "s=socket.socket();s.settimeout(2);"
            "sys.exit(0 if s.connect_ex(('1.1.1.1',53))!=0 else 1)"
        )
        res = self.sb.run(["/usr/bin/python3", "-c", code], SandboxPolicy())
        # exit 0 means connect failed (good: network is blocked)
        self.assertEqual(res.exit_code, 0, res.to_dict())
        self.assertTrue(res.isolation.network_blocked)

    def test_pid_namespace_isolation(self):
        # Inside a PID namespace the process tree is tiny; host PIDs are hidden.
        res = self.sb.run(["/bin/ls", "/proc"], SandboxPolicy())
        pids = [x for x in res.stdout_text().split() if x.isdigit()]
        self.assertLess(len(pids), 20, f"too many visible PIDs: {pids}")

    def test_cannot_write_system(self):
        res = self.sb.run(["/usr/bin/touch", "/usr/should_fail"], SandboxPolicy())
        self.assertNotEqual(res.exit_code, 0)

    def test_workdir_is_writable(self):
        res = self.sb.run(["/usr/bin/touch", "/work/ok"], SandboxPolicy())
        self.assertEqual(res.exit_code, 0, res.to_dict())


class FactoryTests(unittest.TestCase):
    def test_selects_strongest(self):
        sb = create_sandbox(SandboxPolicy())
        self.assertIn(sb.name, {"bubblewrap", "subprocess"})

    def test_untrusted_requires_isolation(self):
        policy = SandboxPolicy(allow_untrusted_execution=True)
        caps = detect_capabilities()
        if caps.can_run_untrusted():
            sb = create_sandbox(policy)
            self.assertTrue(sb.supports_untrusted())
        else:
            with self.assertRaises(SandboxUnavailable):
                create_sandbox(policy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
