"""Action gate tests: capability plus a live approval, or nothing."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.security.approvals import ApprovalLedger  # noqa: E402
from reverseai.security.capabilities import (  # noqa: E402
    CapabilityDenied, CapabilityPolicy,
)
from reverseai.security.gate import ActionGate, GateError  # noqa: E402

ENV = {
    "REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES": "1",
    "REVERSEAI_ENABLE_PAYMENTS": "1",
    "REVERSEAI_VAULT_KEY": "v" * 32,
    "REVERSEAI_APPROVAL_KEY": "a" * 32,
}


class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = ApprovalLedger(Path(self.tmp.name) / "approvals", env=ENV)
        self.gate = ActionGate(CapabilityPolicy(ENV), self.ledger,
                               Path(self.tmp.name) / "audit.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_disabled_capability_is_refused(self):
        gate = ActionGate(CapabilityPolicy({}), None,
                          Path(self.tmp.name) / "a.jsonl")
        with self.assertRaises(CapabilityDenied):
            gate.authorize("payments", "charge", "invoice:1")

    def test_approval_is_required(self):
        with self.assertRaises(GateError):
            self.gate.authorize("payments", "charge", "invoice:1")

    def test_scoped_approval_allows_once(self):
        grant = self.ledger.grant("charge", "invoice:1")
        decision = self.gate.authorize("payments", "charge", "invoice:1",
                                       grant.token)
        self.assertTrue(decision.allowed)
        with self.assertRaises(GateError):
            self.gate.authorize("payments", "charge", "invoice:1", grant.token)

    def test_wrong_scope_is_refused(self):
        grant = self.ledger.grant("charge", "invoice:1")
        with self.assertRaises(GateError):
            self.gate.authorize("payments", "charge", "invoice:2", grant.token)

    def test_audit_is_written(self):
        grant = self.ledger.grant("charge", "invoice:1")
        self.gate.authorize("payments", "charge", "invoice:1", grant.token)
        rows = (Path(self.tmp.name) / "audit.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 1)
        row = json.loads(rows[0])
        self.assertTrue(row["allowed"])
        self.assertEqual(row["capability"], "payments")


if __name__ == "__main__":
    unittest.main(verbosity=2)
