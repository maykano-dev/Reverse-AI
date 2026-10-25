"""Model routing, tool manifests, capability measurement, missions, and trust.

These are the control-plane pieces that let a large system use many models and
tools without losing the evidence boundary. None of them grants authority by
itself; execution still goes through the mediator, sandbox, capability policy,
and approval gate.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..agent.tools import Permission, Tool


# ---------------------------------------------------------------------------
# Model intelligence router
# ---------------------------------------------------------------------------

@dataclass
class ModelProfile:
    name: str
    provider: str
    model: str
    capabilities: list[str] = field(default_factory=list)
    cost_per_mtok: float = 0.0
    latency_ms: int = 1000
    context_tokens: int = 8192
    local: bool = False
    privacy: str = "cloud"       # local | private-cloud | cloud
    success_rate: float = 0.5    # measured, not assumed
    samples: int = 0
    available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RouteDecision:
    profile: ModelProfile | None
    task: str
    rationale: str
    rejected: list[dict[str, Any]] = field(default_factory=list)
    needs_independent_evidence: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict() if self.profile else None,
            "task": self.task, "rationale": self.rationale,
            "rejected": self.rejected,
            "needs_independent_evidence": self.needs_independent_evidence,
        }


class ModelRouter:
    def __init__(self, profiles: list[ModelProfile] | None = None) -> None:
        self.profiles = profiles or []

    def add(self, profile: ModelProfile) -> None:
        self.profiles.append(profile)

    def select(self, task: str, *, required: list[str] | None = None,
               max_cost: float | None = None, max_latency: int | None = None,
               privacy: str | None = None) -> RouteDecision:
        required = set(required or [])
        viable = []
        rejected = []
        for p in self.profiles:
            why = []
            if not p.available:
                why.append("unavailable")
            missing = sorted(required - set(p.capabilities))
            if missing:
                why.append("missing capabilities: " + ", ".join(missing))
            if max_cost is not None and p.cost_per_mtok > max_cost:
                why.append(f"cost {p.cost_per_mtok} > {max_cost}")
            if max_latency is not None and p.latency_ms > max_latency:
                why.append(f"latency {p.latency_ms} > {max_latency}")
            if privacy == "local" and not p.local:
                why.append("privacy requires local execution")
            if why:
                rejected.append({"name": p.name, "why": why})
            else:
                viable.append(p)
        if not viable:
            return RouteDecision(None, task,
                                 "No model satisfies the stated constraints.",
                                 rejected)
        def score(p: ModelProfile) -> float:
            measured = p.success_rate if p.samples else 0.5
            cost = 1.0 / (1.0 + p.cost_per_mtok)
            latency = 1.0 / (1.0 + p.latency_ms / 1000.0)
            return measured * 0.6 + cost * 0.2 + latency * 0.2
        best = max(viable, key=score)
        rationale = (
            f"{best.name} fits the required capabilities and constraints. "
            f"Score {score(best):.3f}; success rate "
            f"{best.success_rate:.0%} from {best.samples} measured sample(s). "
            "The router does not treat model agreement as verification.")
        return RouteDecision(best, task, rationale, rejected)

    def route(self, task: str, call: Callable[[ModelProfile], Any], *,
              required: list[str] | None = None,
              max_cost: float | None = None,
              max_latency: int | None = None,
              privacy: str | None = None) -> Any:
        decision = self.select(task, required=required, max_cost=max_cost,
                               max_latency=max_latency, privacy=privacy)
        if decision.profile is None:
            raise RuntimeError(decision.rationale)
        return call(decision.profile)


# ---------------------------------------------------------------------------
# Universal tool protocol
# ---------------------------------------------------------------------------

@dataclass
class ToolManifest:
    name: str
    description: str
    permission: str
    parameters: dict[str, Any]
    version: str = "1"
    resources: list[str] = field(default_factory=list)
    security_boundary: str = ""
    side_effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_tool(cls, tool: Tool) -> "ToolManifest":
        return cls(
            tool.name, tool.description[:1000], tool.permission.label,
            tool.parameters, "1",
            resources=["cpu"],
            security_boundary=("target execution is sandboxed"
                               if tool.permission >= Permission.EXECUTE
                               else "pure analysis / workspace read"),
            side_effects=(["writes workspace files"]
                          if tool.permission >= Permission.WRITE else []),
        )


def export_manifests(tools: list[Tool]) -> list[dict[str, Any]]:
    return [ToolManifest.from_tool(t).to_dict() for t in tools]


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    problems = []
    if not manifest.get("name"):
        problems.append("missing name")
    if manifest.get("permission") not in [p.label for p in Permission]:
        problems.append("invalid permission")
    if not isinstance(manifest.get("parameters"), dict):
        problems.append("parameters must be a JSON schema object")
    if not manifest.get("security_boundary"):
        problems.append("missing security boundary")
    return problems


# ---------------------------------------------------------------------------
# Capability discovery system
# ---------------------------------------------------------------------------

@dataclass
class CapabilityRecord:
    task_class: str
    attempts: int = 0
    verified: int = 0
    failures: dict[str, int] = field(default_factory=dict)
    total_cost_usd: float = 0.0
    total_seconds: float = 0.0
    tools: list[str] = field(default_factory=list)
    independently_checked: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def success_rate(self) -> float | None:
        return round(self.verified / self.attempts, 3) if self.attempts else None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["success_rate"] = self.success_rate
        return d


class CapabilityMap:
    def __init__(self, min_samples: int = 5) -> None:
        self.records: dict[str, CapabilityRecord] = {}
        self.min_samples = min_samples

    def record(self, task_class: str, *, verified: bool, cost: float = 0.0,
               seconds: float = 0.0, tools: list[str] | None = None,
               failure_mode: str = "", independent: bool = False) -> CapabilityRecord:
        rec = self.records.setdefault(task_class, CapabilityRecord(task_class))
        rec.attempts += 1
        rec.verified += 1 if verified else 0
        rec.total_cost_usd = round(rec.total_cost_usd + cost, 6)
        rec.total_seconds = round(rec.total_seconds + seconds, 3)
        if failure_mode:
            rec.failures[failure_mode] = rec.failures.get(failure_mode, 0) + 1
        if tools:
            rec.tools = sorted(set(rec.tools) | set(tools))
        if independent:
            rec.independently_checked += 1
        rec.last_updated = time.time()
        return rec

    def weakest(self) -> list[dict[str, Any]]:
        rows = [r for r in self.records.values() if r.attempts]
        rows.sort(key=lambda r: (r.success_rate if r.success_rate is not None else 0,
                                 -r.attempts))
        out = []
        for r in rows[:10]:
            row = r.to_dict()
            if r.attempts < self.min_samples:
                row["success_rate"] = None
            out.append(row)
        return out

    def summary(self) -> dict[str, Any]:
        attempts = sum(r.attempts for r in self.records.values())
        verified = sum(r.verified for r in self.records.values())
        publish = attempts >= self.min_samples
        return {
            "task_classes": len(self.records),
            "attempts": attempts,
            "verified": verified,
            "verified_rate": round(verified / attempts, 3) if publish else None,
            "published": publish,
            "weakest": self.weakest(),
            "note": ("a rate is published only after enough attempts; below "
                     "the minimum the result is qualitative, not a percentage"),
        }


# ---------------------------------------------------------------------------
# Mission control and economy
# ---------------------------------------------------------------------------

@dataclass
class Mission:
    id: str
    objective: str
    acceptance: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    budget_usd: float = 0.0
    deadline_s: float = 0.0
    phases: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)
    status: str = "planned"       # planned | running | paused | done | failed
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MissionPlanner:
    def plan(self, objective: str, *, acceptance: list[str] | None = None,
             constraints: list[str] | None = None, budget_usd: float = 0.0,
             deadline_s: float = 0.0) -> Mission:
        phases = [
            {"id": "scope", "title": "Scope and acceptance",
             "exit": "acceptance criteria are explicit"},
            {"id": "model", "title": "Build the world model",
             "exit": "components and unknowns are recorded"},
            {"id": "discover", "title": "Discover opportunities and risks",
             "exit": "ranked, evidence-backed list"},
            {"id": "experiment", "title": "Run discriminating experiments",
             "exit": "hypotheses updated by evidence"},
            {"id": "change", "title": "Implement on a copy",
             "exit": "checkpoint + bounded change"},
            {"id": "verify", "title": "Independent verification",
             "exit": "acceptance and regression tests pass"},
            {"id": "deliver", "title": "Deliver with proof and rollback",
             "exit": "signed package + tested rollback"},
        ]
        gates = ["scope", "change", "deliver"]
        return Mission(
            f"mission_{uuid.uuid4().hex[:10]}", objective[:4000],
            list(acceptance or []), list(constraints or []),
            max(0.0, budget_usd), max(0.0, deadline_s), phases,
            [p["id"] for p in phases], gates, "planned")


@dataclass
class Budget:
    limit_usd: float = 0.0
    spent_usd: float = 0.0
    limit_seconds: float = 0.0
    spent_seconds: float = 0.0

    def can_afford(self, cost: float, seconds: float = 0.0) -> bool:
        if self.limit_usd and self.spent_usd + cost > self.limit_usd:
            return False
        if self.limit_seconds and self.spent_seconds + seconds > self.limit_seconds:
            return False
        return True

    def spend(self, cost: float, seconds: float = 0.0) -> None:
        self.spent_usd = round(self.spent_usd + max(0.0, cost), 6)
        self.spent_seconds = round(self.spent_seconds + max(0.0, seconds), 3)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InvestigationOption:
    name: str
    cost_usd: float
    seconds: float
    expected_value: float
    confidence: str = "hypothesis"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AutonomousEconomy:
    def choose(self, options: list[InvestigationOption], budget: Budget) -> dict[str, Any]:
        viable = [o for o in options if budget.can_afford(o.cost_usd, o.seconds)]
        ranked = sorted(viable, key=lambda o: o.expected_value / max(0.01, o.cost_usd),
                        reverse=True)
        if not ranked:
            return {"choice": None, "reason": "no option fits the budget",
                    "budget": budget.to_dict()}
        best = ranked[0]
        return {
            "choice": best.to_dict(),
            "reason": (f"best expected value per dollar among {len(viable)} "
                       "affordable option(s)"),
            "ranked": [o.to_dict() for o in ranked],
            "budget": budget.to_dict(),
            "stop_rule": ("stop when expected_value / cost falls below the "
                          "value of another unit of budget"),
        }


# ---------------------------------------------------------------------------
# Trust engine
# ---------------------------------------------------------------------------

@dataclass
class TrustDecision:
    action: str
    tier: str                 # auto | notify | approve | forbid
    approval_required: bool
    reason: str
    reversible: bool = True
    blast_radius: str = "local"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HumanDecision:
    question: str
    options: list[str]
    why_human: str
    can_continue: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HumanEscalation:
    """Name the exact decision that needs a human, and continue what can be done."""

    def identify(self, *, physical: bool = False, authorization: bool = False,
                 irreversible: bool = False, domain_expertise: bool = False,
                 legal: bool = False, question: str = "Approve this action?",
                 options: list[str] | None = None) -> HumanDecision | None:
        reasons = []
        if physical:
            reasons.append("physical safety or equipment")
        if authorization:
            reasons.append("authorization the agent does not possess")
        if irreversible:
            reasons.append("an irreversible consequence")
        if domain_expertise:
            reasons.append("domain judgment beyond the available evidence")
        if legal:
            reasons.append("legal or regulatory ownership")
        if not reasons:
            return None
        return HumanDecision(
            question, list(options or ["approve", "reject", "ask for more evidence"]),
            "; ".join(reasons),
            can_continue=not physical and not authorization)


@dataclass
class CompressionStage:
    task: str
    tier: str                 # deterministic | small-model | strong-model | human
    why: str
    quality_check: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IntelligenceCompressor:
    """Plan cheap-first execution with a quality floor, not blind thrift."""

    def plan(self, task: str, *, ambiguity: str = "low",
             risk: str = "low", needs_reasoning: bool = False) -> dict[str, Any]:
        stages = [
            CompressionStage(task, "deterministic",
                             "known algorithm or tool can answer exactly",
                             "compare against a reference result"),
        ]
        if ambiguity != "low" or needs_reasoning:
            stages.append(CompressionStage(
                task, "strong-model", "ambiguity or reasoning justifies it",
                "independent verifier or executable test"))
        else:
            stages.append(CompressionStage(
                task, "small-model", "routine classification/generation",
                "sample audit and acceptance tests"))
        if risk in ("high", "critical"):
            stages.append(CompressionStage(
                task, "human", "consequential decision", "explicit approval"))
        return {
            "task": task,
            "stages": [s.to_dict() for s in stages],
            "rule": "use the cheapest stage that meets the quality floor; "
                    "never trade a verified result for a cheaper unverified one",
        }


class TrustEngine:
    """Risk tiering, not a replacement for the capability and approval gates."""

    def classify(self, action: str, *, reversible: bool = True,
                 blast_radius: str = "local", external: bool = False,
                 sensitive_data: bool = False,
                 financial: bool = False) -> TrustDecision:
        score = 0
        if not reversible:
            score += 3
        if blast_radius in ("service", "organization"):
            score += 2
        if blast_radius == "production":
            score += 3
        if external:
            score += 2
        if sensitive_data:
            score += 2
        if financial:
            score += 3
        if score >= 5:
            tier, approval = "forbid", True
            reason = "irreversible or high-blast-radius action needs a human owner"
        elif score >= 3:
            tier, approval = "approve", True
            reason = "consequential action; require a scoped, live approval"
        elif score >= 1:
            tier, approval = "notify", False
            reason = "observable but reversible; record it in the audit trail"
        else:
            tier, approval = "auto", False
            reason = "local, reversible, no sensitive data or external effect"
        return TrustDecision(action, tier, approval, reason, reversible, blast_radius)
