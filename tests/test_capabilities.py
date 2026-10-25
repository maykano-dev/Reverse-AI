"""High-risk capability policy tests — deny by default, explicit opt-in only."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.security.capabilities import (  # noqa: E402
    CAPABILITIES,
    CapabilityDenied,
    CapabilityPolicy,
)


class CapabilityPolicyTests(unittest.TestCase):
    def test_everything_is_denied_by_default(self):
        policy = CapabilityPolicy({})
        for name in CAPABILITIES:
            self.assertFalse(policy.allowed(name), name)
        with self.assertRaises(CapabilityDenied):
            policy.require("credential_vault")

    def test_specific_opt_in_without_master_is_not_enough(self):
        policy = CapabilityPolicy({"REVERSEAI_ENABLE_REMOTE_CONTROL": "1"})
        self.assertFalse(policy.allowed("remote_control"))
        self.assertIn("REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES", policy.decision(
            "remote_control").reason)

    def test_master_plus_specific_opt_in(self):
        policy = CapabilityPolicy({
            "REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES": "1",
            "REVERSEAI_ENABLE_REMOTE_CONTROL": "1",
        })
        self.assertTrue(policy.allowed("remote_control"))
        self.assertFalse(policy.allowed("credential_vault"))

    def test_vault_requires_a_key(self):
        policy = CapabilityPolicy({
            "REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES": "1",
            "REVERSEAI_ENABLE_CREDENTIAL_VAULT": "1",
        })
        self.assertFalse(policy.allowed("credential_vault"))
        self.assertIn("REVERSEAI_VAULT_KEY", policy.decision(
            "credential_vault").reason)
        policy = CapabilityPolicy({
            "REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES": "1",
            "REVERSEAI_ENABLE_CREDENTIAL_VAULT": "1",
            "REVERSEAI_VAULT_KEY": "secret",
        })
        self.assertTrue(policy.allowed("credential_vault"))

    def test_status_is_structured(self):
        status = CapabilityPolicy({}).status()
        self.assertIn("desktop_workstation", status)
        self.assertFalse(status["desktop_workstation"]["allowed"])
        self.assertEqual(status["desktop_workstation"]["risk"], "high")


if __name__ == "__main__":
    unittest.main(verbosity=2)
