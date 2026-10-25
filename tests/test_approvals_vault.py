"""Approval ledger and optional encrypted vault tests."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.security.approvals import (  # noqa: E402
    ApprovalError, ApprovalLedger,
)
from reverseai.security.capabilities import CapabilityDenied  # noqa: E402
from reverseai.security.vault import Vault, VaultError, VaultUnavailable  # noqa: E402

CRYPTO = importlib.util.find_spec("cryptography") is not None
ENV = {"REVERSEAI_APPROVAL_KEY": "a" * 32}
VAULT_ENV = {
    "REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES": "1",
    "REVERSEAI_ENABLE_CREDENTIAL_VAULT": "1",
    "REVERSEAI_VAULT_KEY": "v" * 32,
}


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = ApprovalLedger(Path(self.tmp.name) / "approvals", env=ENV)

    def tearDown(self):
        self.tmp.cleanup()

    def test_grant_and_consume_once(self):
        grant = self.ledger.grant("payments.charge", "invoice:123", "user approved")
        approval = self.ledger.consume(grant.token, "payments.charge", "invoice:123")
        self.assertEqual(approval.action, "payments.charge")
        with self.assertRaises(ApprovalError):
            self.ledger.consume(grant.token, "payments.charge", "invoice:123")

    def test_wrong_action_is_refused(self):
        grant = self.ledger.grant("desktop.takeover", "host:1")
        with self.assertRaises(ApprovalError):
            self.ledger.consume(grant.token, "payments.charge")

    def test_tampered_token_is_refused(self):
        grant = self.ledger.grant("remote.run")
        body, mac = grant.token.split(".")
        tampered = body + "x." + mac
        with self.assertRaises(ApprovalError):
            self.ledger.consume(tampered, "remote.run")

    def test_expired_token_is_refused(self):
        grant = self.ledger.grant("remote.run", ttl_seconds=1)
        time.sleep(1.1)
        with self.assertRaises(ApprovalError):
            self.ledger.consume(grant.token, "remote.run")

    def test_missing_key_refuses_to_issue(self):
        ledger = ApprovalLedger(Path(self.tmp.name) / "other", env={})
        with self.assertRaises(ApprovalError):
            ledger.grant("remote.run")

    def test_pending_excludes_used(self):
        grant = self.ledger.grant("remote.run", max_uses=2)
        self.assertEqual(len(self.ledger.pending()), 1)
        self.ledger.consume(grant.token, "remote.run")
        self.assertEqual(len(self.ledger.pending()), 1)
        self.ledger.consume(grant.token, "remote.run")
        self.assertEqual(len(self.ledger.pending()), 0)


@unittest.skipUnless(CRYPTO, "optional cryptography package is absent")
class VaultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "vault.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_and_no_plaintext(self):
        vault = Vault(self.path, "v" * 32, env=VAULT_ENV)
        vault.put("api-key", "super-secret-value")
        self.assertEqual(vault.get("api-key"), "super-secret-value")
        self.assertIn("api-key", vault.names())
        blob = self.path.read_text()
        self.assertNotIn("super-secret-value", blob)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_wrong_key_cannot_decrypt(self):
        Vault(self.path, "v" * 32, env=VAULT_ENV).put("x", "y")
        vault = Vault(self.path, "w" * 32, env=VAULT_ENV)
        with self.assertRaises(VaultError):
            vault.get("x")

    def test_capability_is_required(self):
        with self.assertRaises(CapabilityDenied):
            Vault(self.path, "v" * 32, env={})

    def test_short_key_is_refused(self):
        with self.assertRaises(VaultError):
            Vault(self.path, "short", env=VAULT_ENV)

    def test_delete(self):
        vault = Vault(self.path, "v" * 32, env=VAULT_ENV)
        vault.put("x", "y")
        self.assertTrue(vault.delete("x"))
        self.assertFalse(vault.delete("x"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
