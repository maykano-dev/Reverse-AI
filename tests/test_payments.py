"""Payment ledger: capability, idempotency, limits, and approval."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.payments.ledger import (  # noqa: E402
    HttpPaymentProvider, MockPaymentProvider, PaymentLedger, PaymentRefused,
)
from reverseai.security.approvals import ApprovalLedger  # noqa: E402
from reverseai.security.capabilities import CapabilityPolicy  # noqa: E402

ENV = {
    "REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES": "1",
    "REVERSEAI_ENABLE_PAYMENTS": "1",
    "REVERSEAI_VAULT_KEY": "v" * 32,
    "REVERSEAI_APPROVAL_KEY": "a" * 32,
}


class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.policy = CapabilityPolicy(ENV)
        self.approvals = ApprovalLedger(Path(self.tmp.name) / "approvals", env=ENV)
        self.ledger = PaymentLedger(
            Path(self.tmp.name) / "payments.json",
            policy=self.policy, ledger=self.approvals,
            provider=MockPaymentProvider(), max_amount_cents=5000)

    def tearDown(self):
        self.tmp.cleanup()

    def test_denied_by_default(self):
        ledger = PaymentLedger(Path(self.tmp.name) / "d.json",
                               policy=CapabilityPolicy({}),
                               provider=MockPaymentProvider())
        with self.assertRaises(PaymentRefused):
            ledger.create(100, "USD", "x")

    def test_idempotency_and_limit(self):
        a = self.ledger.create(100, "usd", "one", idempotency_key="same")
        b = self.ledger.create(100, "USD", "one", idempotency_key="same")
        self.assertEqual(a.id, b.id)
        with self.assertRaises(PaymentRefused):
            self.ledger.create(5001, "USD", "too much")

    def test_charge_requires_approval_and_is_idempotent(self):
        intent = self.ledger.create(250, "USD", "data", scope="invoice:1")
        with self.assertRaises(PaymentRefused):
            self.ledger.charge(intent.id, "not-a-token")
        grant = self.approvals.grant("payments.charge", "invoice:1")
        out = self.ledger.charge(intent.id, grant.token)
        self.assertTrue(out["ok"])
        self.assertTrue(out["provider"]["live"] is False)
        again = self.ledger.charge(intent.id, grant.token)
        self.assertTrue(again["idempotent"])
        self.assertEqual(self.ledger.summary()["charged"], 1)

    def test_wrong_scope_is_refused(self):
        intent = self.ledger.create(250, "USD", "data", scope="invoice:1")
        grant = self.approvals.grant("payments.charge", "invoice:2")
        with self.assertRaises(PaymentRefused):
            self.ledger.charge(intent.id, grant.token)

    def test_no_card_fields_are_accepted(self):
        intent = self.ledger.create(1, "USD", "no card")
        self.assertNotIn("card", intent.to_dict())
        self.assertNotIn("cvv", intent.to_dict())

    def test_http_provider_never_sends_card_data(self):
        calls = []

        def transport(path, payload):
            calls.append((path, payload))
            return {"ok": True, "provider_id": "p1", "live": False}

        provider = HttpPaymentProvider("https://payments.example.test",
                                       token="t", transport=transport)
        intent = self.ledger.create(100, "USD", "data")
        provider.charge(intent)
        path, payload = calls[0]
        self.assertEqual(path, "/charge")
        self.assertNotIn("card", payload)
        self.assertNotIn("cvv", payload)
        self.assertEqual(payload["idempotency_key"], intent.idempotency_key)

    def test_http_provider_refuses_insecure_remote_endpoint(self):
        with self.assertRaises(PaymentRefused):
            HttpPaymentProvider("http://payments.example.test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
