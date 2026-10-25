"""Deployment is a plan, a dry run, an approval, and a tested rollback.

No cloud provider or SSH client is bundled. A transport is injected by the
operator. The controller refuses unless the deployment capability is enabled and
a live, scoped approval is consumed for the exact target.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from ..security.approvals import ApprovalError, ApprovalLedger
from ..security.capabilities import CapabilityDenied, CapabilityPolicy
from ..security.gate import ActionGate, GateError


class DeploymentRefused(Exception):
    pass


@dataclass
class DeploymentPlan:
    id: str
    target: str
    artifact: str
    steps: list[str] = field(default_factory=list)
    rollback: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=lambda: ["deploy"])
    status: str = "planned"       # planned | dry_run | deployed | rolled_back | failed
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeploymentResult:
    plan_id: str
    status: str
    ok: bool
    output: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Transport = Callable[[str, DeploymentPlan], dict[str, Any]]


class HttpDeploymentTransport:
    """Operator-supplied deployment webhook.

    It sends a plan id, target, artifact, and action. It does not contain cloud
    credentials and it never deploys by itself.
    """

    def __init__(self, endpoint: str, token: str = "",
                 transport: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
                 timeout: float = 30.0) -> None:
        if not endpoint.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise DeploymentRefused("deployment endpoint must be HTTPS or loopback")
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout
        self._transport = transport

    def __call__(self, action: str, plan: DeploymentPlan) -> dict[str, Any]:
        payload = {"action": action, "plan": plan.id, "target": plan.target,
                   "artifact": plan.artifact, "steps": plan.steps,
                   "rollback": plan.rollback}
        if self._transport is not None:
            return self._transport(action, payload)
        import json
        import urllib.request

        req = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.token}"} if self.token else {})},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            raise DeploymentRefused(f"deployment endpoint failed: {exc}") from exc


class DeploymentController:
    def __init__(self, *, policy: CapabilityPolicy | None = None,
                 ledger: ApprovalLedger | None = None,
                 transport: Transport | None = None,
                 audit_path: str | None = None) -> None:
        self.policy = policy or CapabilityPolicy()
        self.ledger = ledger
        self.transport = transport
        self.audit_path = audit_path
        self.plans: dict[str, DeploymentPlan] = {}

    def plan(self, target: str, artifact: str, *,
             steps: list[str] | None = None,
             rollback: list[str] | None = None) -> DeploymentPlan:
        try:
            self.policy.require("deployment")
        except CapabilityDenied as exc:
            raise DeploymentRefused(str(exc)) from exc
        if not target or not artifact:
            raise DeploymentRefused("target and artifact are required")
        plan = DeploymentPlan(
            "dep_" + uuid.uuid4().hex[:10], target[:500], artifact[:1000],
            list(steps or ["upload artifact", "run smoke tests", "switch traffic"]),
            list(rollback or ["switch traffic back", "restore previous artifact"]))
        self.plans[plan.id] = plan
        return plan

    def dry_run(self, plan_id: str) -> DeploymentResult:
        plan = self.plans.get(plan_id)
        if plan is None:
            raise DeploymentRefused("unknown deployment plan")
        plan.status = "dry_run"
        return DeploymentResult(plan.id, "dry_run", True,
                                {"steps": plan.steps, "rollback": plan.rollback,
                                 "target": plan.target, "artifact": plan.artifact},
                                "dry run only; nothing was deployed")

    def deploy(self, plan_id: str, *, approval_token: str | None = None) -> DeploymentResult:
        plan = self.plans.get(plan_id)
        if plan is None:
            raise DeploymentRefused("unknown deployment plan")
        try:
            self.policy.require("deployment")
        except CapabilityDenied as exc:
            raise DeploymentRefused(str(exc)) from exc
        if self.ledger is None:
            raise DeploymentRefused("no approval ledger is configured")
        gate = ActionGate(self.policy, self.ledger, self.audit_path)
        try:
            gate.authorize("deployment", "deployment.deploy", plan.target,
                           approval_token)
        except (CapabilityDenied, GateError, ApprovalError) as exc:
            plan.status = "failed"
            raise DeploymentRefused(str(exc)) from exc
        if self.transport is None:
            plan.status = "failed"
            raise DeploymentRefused("no deployment transport is configured")
        try:
            output = self.transport("deploy", plan)
        except Exception as exc:
            plan.status = "failed"
            raise DeploymentRefused(f"deployment transport failed: {exc}") from exc
        plan.status = "deployed" if output.get("ok") else "failed"
        return DeploymentResult(plan.id, plan.status, bool(output.get("ok")),
                                output, "" if output.get("ok") else "transport refused")

    def rollback(self, plan_id: str, *, approval_token: str | None = None) -> DeploymentResult:
        plan = self.plans.get(plan_id)
        if plan is None:
            raise DeploymentRefused("unknown deployment plan")
        if self.ledger is None:
            raise DeploymentRefused("no approval ledger is configured")
        gate = ActionGate(self.policy, self.ledger, self.audit_path)
        try:
            gate.authorize("deployment", "deployment.rollback", plan.target,
                           approval_token)
        except (CapabilityDenied, GateError, ApprovalError) as exc:
            raise DeploymentRefused(str(exc)) from exc
        if self.transport is None:
            raise DeploymentRefused("no deployment transport is configured")
        output = self.transport("rollback", plan)
        plan.status = "rolled_back" if output.get("ok") else "failed"
        return DeploymentResult(plan.id, plan.status, bool(output.get("ok")),
                                output)
