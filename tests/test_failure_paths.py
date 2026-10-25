"""Failure paths that must fail closed, not silently fall back."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.sandbox.factory import create_sandbox  # noqa: E402
from reverseai.sandbox.policy import SandboxPolicy  # noqa: E402
from reverseai.verify.difftest import InputCase, run_differential  # noqa: E402


class FailClosedTests(unittest.TestCase):
    def test_differential_refuses_when_no_sandbox_is_available(self):
        with mock.patch("reverseai.verify.difftest.create_sandbox",
                        side_effect=RuntimeError("no backend")):
            report = run_differential("/bin/true", "/bin/true",
                                      [InputCase("smoke", [])])
        self.assertFalse(report.ran)
        self.assertIn("sandbox", (report.error or "").lower())

    def test_factory_refuses_untrusted_execution_without_a_backend(self):
        with mock.patch("reverseai.sandbox.factory.available_backends",
                        return_value=[]):
            with self.assertRaises(Exception) as ctx:
                create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        self.assertIn("backend", str(ctx.exception).lower())

    def test_factory_does_not_silently_use_a_host_backend(self):
        with mock.patch("reverseai.sandbox.factory.available_backends",
                        return_value=[]):
            with self.assertRaises(Exception):
                create_sandbox(SandboxPolicy(allow_untrusted_execution=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
