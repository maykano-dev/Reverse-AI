"""Repository audit invariants."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.audit import Check, AuditReport, run_audit  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class AuditTests(unittest.TestCase):
    def test_repository_passes_its_own_audit(self):
        report = run_audit(ROOT)
        self.assertTrue(report.ok,
                        "\n".join(f"{c.name}: {c.detail}"
                                  for c in report.checks if not c.ok))
        self.assertGreaterEqual(len(report.checks), 10)

    def test_audit_renders_and_serializes(self):
        report = run_audit(ROOT)
        self.assertIn("PASS", report.render())
        data = json.loads(json.dumps(report.to_dict()))
        self.assertTrue(data["ok"])
        self.assertIn("checks", data)

    def test_a_failing_check_makes_the_report_fail(self):
        report = AuditReport("/tmp")
        report.checks = [Check("good", True), Check("bad", False, "why")]
        self.assertFalse(report.ok)
        self.assertIn("FAIL", report.render())


if __name__ == "__main__":
    unittest.main(verbosity=2)
