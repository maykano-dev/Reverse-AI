"""A controlled improvement pipeline.

Observe → record → propose → benchmark → holdout → human approve → deploy →
monitor → roll back. The pipeline never trains or deploys automatically.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from ..security.approvals import ApprovalError, ApprovalLedger
from ..security.capabilities import CapabilityDenied, CapabilityPolicy
from ..security.gate import ActionGate, GateError


@dataclass
class TrainingPlan:
    baseline: str
    candidate: str
    hypothesis: str
    benchmark_metric: str = "verified_rate"
    holdout_cases: int = 0
    gates: list[str] = field(default_factory=lambda: [
        "benchmark improves over baseline",
        "holdout improves without regression",
        "security review passes",
        "human approval recorded",
        "rollback plan tested",
    ])
    status: str = "draft"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImprovementProposal:
    id: str
    hypothesis: str
    change: str
    plan: TrainingPlan
    baseline_metrics: dict[str, float] = field(default_factory=dict)
    candidate_metrics: dict[str, float] = field(default_factory=dict)
    holdout_metrics: dict[str, float] = field(default_factory=dict)
    status: str = "proposed"      # proposed | rejected | approved | rolled_back
    reason: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "plan": self.plan.to_dict()}


class ImprovementPipeline:
    def __init__(self, policy: CapabilityPolicy | None = None,
                 ledger: ApprovalLedger | None = None,
                 audit_path: str | None = None) -> None:
        self.policy = policy or CapabilityPolicy()
        self.ledger = ledger
        self.audit_path = audit_path
        self.proposals: dict[str, ImprovementProposal] = {}

    def propose(self, hypothesis: str, change: str, *,
                baseline: str = "current",
                candidate: str = "candidate",
                holdout_cases: int = 0) -> ImprovementProposal:
        try:
            self.policy.require("self_training")
        except CapabilityDenied as exc:
            raise PermissionError(str(exc)) from exc
        plan = TrainingPlan(baseline, candidate, hypothesis,
                            holdout_cases=holdout_cases)
        proposal = ImprovementProposal(
            "imp_" + uuid.uuid4().hex[:10], hypothesis, change, plan)
        self.proposals[proposal.id] = proposal
        return proposal

    def evaluate(self, proposal_id: str, *,
                 baseline: dict[str, float],
                 candidate: dict[str, float],
                 holdout: dict[str, float],
                 metric: str = "verified_rate",
                 require_holdout: bool = True) -> ImprovementProposal:
        p = self.proposals.get(proposal_id)
        if p is None:
            raise KeyError("proposal not found")
        p.baseline_metrics = dict(baseline)
        p.candidate_metrics = dict(candidate)
        p.holdout_metrics = dict(holdout)
        base = baseline.get(metric)
        cand = candidate.get(metric)
        hold = holdout.get(metric)
        reasons = []
        if base is None or cand is None:
            reasons.append(f"metric {metric!r} is missing")
        elif cand <= base:
            reasons.append("candidate did not beat the baseline")
        if require_holdout and hold is None:
            reasons.append("no holdout measurement")
        elif require_holdout and base is not None and hold is not None and hold < base:
            reasons.append("holdout regressed below the baseline")
        if reasons:
            p.status = "rejected"
            p.reason = "; ".join(reasons)
        else:
            p.status = "approved"
            p.reason = ("candidate passed the benchmark and holdout; still "
                        "requires a human deployment approval")
        return p

    def approve(self, proposal_id: str, *, approval_token: str | None = None) -> ImprovementProposal:
        """Promote a measured improvement after a live, scoped approval.

        This is not a deployment. It records the human gate; the deployment
        controller requires its own approval.
        """
        p = self.proposals.get(proposal_id)
        if p is None:
            raise KeyError("proposal not found")
        if p.status != "approved":
            raise PermissionError("only a measured, approved proposal can be promoted")
        if self.ledger is None:
            raise PermissionError("promotion requires an approval ledger")
        gate = ActionGate(self.policy, self.ledger, self.audit_path)
        try:
            gate.authorize("self_training", "self_training.promote",
                           proposal_id, approval_token)
        except (CapabilityDenied, GateError, ApprovalError) as exc:
            raise PermissionError(str(exc)) from exc
        p.reason += " · human gate acknowledged"
        return p

    def rollback(self, proposal_id: str, reason: str) -> ImprovementProposal:
        p = self.proposals.get(proposal_id)
        if p is None:
            raise KeyError("proposal not found")
        p.status = "rolled_back"
        p.reason = f"rolled back: {reason[:500]}"
        return p
