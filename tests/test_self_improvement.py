"""Verified-trace datasets, improvement gates, and deployment boundaries."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.job import Job  # noqa: E402
from reverseai.agent.store import JobStore  # noqa: E402
from reverseai.deploy.controller import (  # noqa: E402
    DeploymentController, DeploymentRefused, HttpDeploymentTransport,
)
from reverseai.security.approvals import ApprovalLedger  # noqa: E402
from reverseai.security.capabilities import CapabilityPolicy  # noqa: E402
from reverseai.training.dataset import extract_traces, redact  # noqa: E402
from reverseai.training.pipeline import ImprovementPipeline  # noqa: E402

TRAIN_ENV = {
    "REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES": "1",
    "REVERSEAI_ENABLE_SELF_TRAINING": "1",
    "REVERSEAI_ENABLE_DEPLOYMENT": "1",
    "REVERSEAI_APPROVAL_KEY": "a" * 32,
}


def make_store(td: str) -> JobStore:
    store = JobStore(td)
    good = Job(goal="change OLD to NEW", target_path="app", status="completed")
    good.verification = {"verified": True, "passed_tests": 2}
    good.delivery = {"allowed": True}
    good.artifact_meta = {"sha256": "a" * 64, "name": "app.patched"}
    good.evidence.observed("the change was tested")
    good.usage = {"cost_usd": 0.01}
    store.save(good)
    bad = Job(goal="guessed", target_path="app", status="completed")
    bad.verification = {"verified": False}
    bad.delivery = {"allowed": False}
    store.save(bad)
    return store


class DatasetTests(unittest.TestCase):
    def test_only_verified_jobs_are_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            store = make_store(td)
            data = extract_traces(td)
            self.assertEqual(len(data.records), 1)
            self.assertEqual(data.rejected, 1)
            self.assertIn(data.records[0].split, ("train", "holdout"))
            self.assertEqual(data.summary()["records"], 1)

    def test_secret_redaction(self):
        self.assertEqual(redact("api_key=abcdefgh1234"), "[REDACTED]")
        with tempfile.TemporaryDirectory() as td:
            store = make_store(td)
            for path in store.dir.glob("job_*.json"):
                raw = json.loads(path.read_text())
                if (raw.get("verification") or {}).get("verified"):
                    raw["goal"] = "use api_key=abcdefgh1234"
                    path.write_text(json.dumps(raw))
                    break
            data = extract_traces(td)
            self.assertIn("[REDACTED]", data.records[0].goal)

    def test_export_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            make_store(td)
            data = extract_traces(td)
            out = data.export_jsonl(Path(td) / "data.jsonl")
            lines = out.read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("job_id", json.loads(lines[0]))


class ImprovementTests(unittest.TestCase):
    def test_capability_is_required(self):
        pipe = ImprovementPipeline(CapabilityPolicy({}))
        with self.assertRaises(PermissionError):
            pipe.propose("better", "change")

    def test_candidate_must_beat_baseline_and_holdout(self):
        with tempfile.TemporaryDirectory() as td:
            approvals = ApprovalLedger(Path(td) / "approvals", env=TRAIN_ENV)
            pipe = ImprovementPipeline(CapabilityPolicy(TRAIN_ENV),
                                       ledger=approvals)
            p = pipe.propose("better strategy", "change", holdout_cases=10)
            worse = pipe.evaluate(p.id, baseline={"verified_rate": 0.8},
                                  candidate={"verified_rate": 0.7},
                                  holdout={"verified_rate": 0.7})
            self.assertEqual(worse.status, "rejected")
            p2 = pipe.propose("better strategy", "change", holdout_cases=10)
            better = pipe.evaluate(p2.id, baseline={"verified_rate": 0.8},
                                   candidate={"verified_rate": 0.9},
                                   holdout={"verified_rate": 0.85})
            self.assertEqual(better.status, "approved")
            grant = approvals.grant("self_training.promote", p2.id)
            self.assertTrue(pipe.approve(p2.id, approval_token=grant.token).reason)

    def test_holdout_regression_is_rejected(self):
        pipe = ImprovementPipeline(CapabilityPolicy(TRAIN_ENV))
        p = pipe.propose("x", "y", holdout_cases=10)
        out = pipe.evaluate(p.id, baseline={"verified_rate": 0.8},
                            candidate={"verified_rate": 0.9},
                            holdout={"verified_rate": 0.7})
        self.assertEqual(out.status, "rejected")
        self.assertIn("holdout", out.reason)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.policy = CapabilityPolicy(TRAIN_ENV)
        self.approvals = ApprovalLedger(Path(self.tmp.name) / "approvals",
                                        env=TRAIN_ENV)
        self.calls = []
        self.controller = DeploymentController(
            policy=self.policy, ledger=self.approvals,
            transport=lambda action, plan: (
                self.calls.append(action) or {"ok": True, "action": action}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_dry_run_and_approval(self):
        p = self.controller.plan("staging", "app.tar")
        self.assertTrue(self.controller.dry_run(p.id).ok)
        with self.assertRaises(DeploymentRefused):
            self.controller.deploy(p.id)
        grant = self.approvals.grant("deployment.deploy", "staging")
        out = self.controller.deploy(p.id, approval_token=grant.token)
        self.assertTrue(out.ok)
        self.assertEqual(self.calls, ["deploy"])
        self.assertEqual(out.status, "deployed")

    def test_duplicate_deploy_is_blocked_by_single_use_approval(self):
        p = self.controller.plan("staging", "app.tar")
        grant = self.approvals.grant("deployment.deploy", "staging")
        self.assertTrue(self.controller.deploy(p.id, approval_token=grant.token).ok)
        with self.assertRaises(DeploymentRefused):
            self.controller.deploy(p.id, approval_token=grant.token)

    def test_rollback_requires_its_own_approval(self):
        p = self.controller.plan("prod", "app.tar")
        grant = self.approvals.grant("deployment.deploy", "prod")
        self.controller.deploy(p.id, approval_token=grant.token)
        with self.assertRaises(DeploymentRefused):
            self.controller.rollback(p.id)
        rollback = self.approvals.grant("deployment.rollback", "prod")
        out = self.controller.rollback(p.id, approval_token=rollback.token)
        self.assertTrue(out.ok)
        self.assertEqual(out.status, "rolled_back")

    def test_denied_by_default(self):
        c = DeploymentController(policy=CapabilityPolicy({}))
        with self.assertRaises(DeploymentRefused):
            c.plan("prod", "app.tar")

    def test_http_transport_is_injected_and_insecure_remote_is_refused(self):
        calls = []

        def transport(action, payload):
            calls.append((action, payload))
            return {"ok": True}

        http = HttpDeploymentTransport("https://deploy.example.test",
                                       token="t", transport=transport)
        c = DeploymentController(policy=self.policy, ledger=self.approvals,
                                 transport=http)
        p2 = c.plan("staging", "app.tar")
        g2 = self.approvals.grant("deployment.deploy", "staging")
        out = c.deploy(p2.id, approval_token=g2.token)
        self.assertTrue(out.ok)
        self.assertEqual(calls[0][0], "deploy")
        self.assertNotIn("token", calls[0][1])
        with self.assertRaises(DeploymentRefused):
            HttpDeploymentTransport("http://deploy.example.test")


if __name__ == "__main__":
    unittest.main(verbosity=2)
