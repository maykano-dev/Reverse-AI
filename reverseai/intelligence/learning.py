"""Verified skill learning, the intelligence foundry, analogy, and failure review.

Nothing here retrains a model or rewrites the core. It records reusable,
testable procedures and evaluates candidate changes against a baseline, a
holdout, and the previous version. A lesson is promoted only when the evidence
survives a case it was not tuned on.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .world import WorldModel


@dataclass
class Skill:
    id: str
    name: str
    version: int
    steps: list[str]
    tests: list[dict[str, Any]]
    status: str = "candidate"     # candidate | tested | promoted | stale
    inputs: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    environment: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SkillLearner:
    def __init__(self) -> None:
        self.skills: dict[str, Skill] = {}

    def record(self, name: str, steps: list[str], *,
               inputs: dict[str, Any] | None = None,
               limitations: list[str] | None = None,
               environment: str = "") -> Skill:
        skill = Skill(f"skill_{uuid.uuid4().hex[:10]}", name[:200], 1,
                      list(steps)[:50], [], inputs=dict(inputs or {}),
                      limitations=list(limitations or []),
                      environment=environment[:200])
        self.skills[skill.id] = skill
        return skill

    def validate(self, skill: Skill, cases: list[dict[str, Any]],
                 runner: Callable[[dict[str, Any]], Any]) -> Skill:
        passed = failed = 0
        rows = []
        for case in cases:
            try:
                got = runner(dict(case.get("inputs") or {}))
                ok = got == case.get("expect")
                rows.append({"name": case.get("name"), "ok": ok, "got": got})
                passed += 1 if ok else 0
                failed += 0 if ok else 1
            except Exception as exc:
                failed += 1
                rows.append({"name": case.get("name"), "ok": False,
                             "error": f"{type(exc).__name__}: {exc}"})
        skill.tests = rows
        skill.status = "tested" if passed and not failed else "failed"
        return skill

    def promote(self, skill: Skill) -> Skill:
        if skill.status != "tested":
            raise ValueError("only a tested skill can be promoted")
        skill.status = "promoted"
        return skill

    def mark_stale(self, skill: Skill, reason: str) -> Skill:
        skill.status = "stale"
        skill.limitations.append(reason[:500])
        return skill


@dataclass
class CandidateConfig:
    name: str
    config: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    passed_holdout: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FoundryReport:
    baseline: CandidateConfig
    candidates: list[CandidateConfig]
    winner: str
    reason: str
    disqualified: list[str]
    confidence: str
    holdout_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline.to_dict(),
            "candidates": [c.to_dict() for c in self.candidates],
            "winner": self.winner, "reason": self.reason,
            "disqualified": self.disqualified,
            "confidence": self.confidence, "holdout_size": self.holdout_size,
        }


class IntelligenceFoundry:
    """Compare candidates on a benchmark and a separate holdout."""

    def __init__(self, higher_is_better: tuple[str, ...] = ("accuracy", "verified_rate")) -> None:
        self.higher = set(higher_is_better)

    def run(self, baseline: CandidateConfig, candidates: list[CandidateConfig],
            *, holdout_cases: int = 0) -> FoundryReport:
        viable = []
        disqualified = []
        for c in candidates:
            if not c.passed_holdout:
                disqualified.append(f"{c.name}: did not pass the holdout")
                continue
            viable.append(c)
        if not viable:
            return FoundryReport(baseline, candidates, baseline.name,
                                 "no candidate passed the holdout; keep the baseline",
                                 disqualified, "observed", holdout_cases)
        def score(c: CandidateConfig) -> float:
            total = 0.0
            for key, value in c.metrics.items():
                b = baseline.metrics.get(key)
                if b is None:
                    continue
                if key in self.higher:
                    total += (value - b) / max(abs(b), 1e-9)
                else:
                    total += (b - value) / max(abs(b), 1e-9)
            return total
        best = max(viable, key=score)
        delta = score(best)
        reason = (f"{best.name} improves the baseline by {delta:.3f} across "
                  f"{len(best.metrics)} metric(s) and passed {holdout_cases} holdout case(s).")
        if delta <= 0:
            return FoundryReport(baseline, candidates, baseline.name,
                                 "no candidate beat the baseline; do not deploy",
                                 disqualified, "observed", holdout_cases)
        return FoundryReport(baseline, candidates, best.name, reason, disqualified,
                             "observed" if holdout_cases else "hypothesis",
                             holdout_cases)


@dataclass
class Analogy:
    source: str
    target: str
    mapping: dict[str, str]
    score: float
    disanalogies: list[str]
    status: str
    assumptions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeTranslator:
    def compare(self, source: WorldModel, target: WorldModel) -> Analogy:
        src = {n.name.lower(): n for n in source.nodes.values()}
        tgt = {n.name.lower(): n for n in target.nodes.values()}
        mapping = {a: b for a, b in zip(sorted(src), sorted(tgt))}
        shared = len(set(src) & set(tgt))
        score = round(shared / max(1, max(len(src), len(tgt))), 3)
        return Analogy(
            source.name, target.name, mapping, score,
            ["names and degrees of freedom may differ",
             "a structural similarity does not preserve causal mechanisms"],
            "hypothesis",
            ["validate the transferred method on the target's own constraints"])
        # The mapping is a question, not a conclusion.


@dataclass
class FailureReview:
    category: str
    reason: str
    next_action: str
    confidence: str = "hypothesis"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FailureClassifier:
    def classify(self, failure: str, *, context: dict[str, Any] | None = None) -> FailureReview:
        text = (failure or "").lower()
        ctx = context or {}
        if any(w in text for w in ("sandbox", "permission", "denied", "unavailable")):
            return FailureReview("tool", "the environment or tool refused the operation",
                                 "fix the boundary or ask for the missing capability")
        if any(w in text for w in ("not found", "missing", "unknown", "no such")):
            return FailureReview("information", "a required fact or path is missing",
                                 "collect the missing evidence before retrying")
        if any(w in text for w in ("timeout", "budget", "cost", "limit")):
            return FailureReview("compute", "the computation or budget was exhausted",
                                 "narrow the experiment or raise the budget explicitly")
        if any(w in text for w in ("assert", "expect", "mismatch", "regression")):
            return FailureReview("assumption", "a prediction or invariant did not hold",
                                 "revise the model and design a discriminating test")
        if ctx.get("plan_steps", 0) > ctx.get("max_steps", 1):
            return FailureReview("plan", "the plan exceeded its step budget",
                                 "split the mission or reduce scope")
        return FailureReview("model", "no specific cause is established",
                             "collect more observations; do not retry blindly")


@dataclass
class ResearchReport:
    question: str
    competing_explanations: list[str]
    evidence: list[dict[str, Any]]
    experiments: list[dict[str, Any]]
    best_supported: str
    limitations: list[str]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchProgram:
    def plan(self, question: str) -> dict[str, Any]:
        return {
            "question": question,
            "steps": [
                "state competing explanations",
                "find the cheapest discriminating observation",
                "run it in an isolated environment",
                "update or reject each explanation",
                "report the best-supported result and what remains unknown",
            ],
            "stop_condition": "no remaining explanation changes the decision",
        }

    def report(self, question: str, explanations: list[str],
               evidence: list[dict[str, Any]], experiments: list[dict[str, Any]],
               best: str) -> ResearchReport:
        limitations = [
            "the best-supported explanation is not a proof",
            "experiments cover only the declared conditions",
            "published work may not reproduce in this environment",
        ]
        return ResearchReport(question, explanations, evidence, experiments,
                              best, limitations,
                              "observed" if evidence else "unknown")


@dataclass
class GeneralizationReport:
    train_passed: int
    train_total: int
    holdout_passed: int
    holdout_total: int
    variation_axes: list[str]
    failures: list[dict[str, Any]]
    verdict: str
    overfit_suspected: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GeneralizationEngine:
    """Check whether a capability survives cases it was not tuned on."""

    def evaluate(self, train: list[dict[str, Any]],
                 holdout: list[dict[str, Any]],
                 runner: Callable[[dict[str, Any]], Any],
                 *, variation_axes: list[str] | None = None) -> GeneralizationReport:
        def run(cases: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
            passed = 0
            failures = []
            for case in cases:
                try:
                    got = runner(dict(case.get("inputs") or {}))
                    ok = got == case.get("expect")
                except Exception as exc:
                    ok = False
                    failures.append({"name": case.get("name"),
                                     "error": f"{type(exc).__name__}: {exc}"})
                    continue
                if ok:
                    passed += 1
                else:
                    failures.append({"name": case.get("name"),
                                     "got": got, "expected": case.get("expect")})
            return passed, failures

        tp, tf = run(train)
        hp, hf = run(holdout)
        failures = tf + hf
        overfit = bool(tp == len(train) and train and hp < len(holdout))
        if overfit:
            verdict = ("training cases pass but the holdout fails: memorize is "
                       "not generalization")
        elif holdout and hp == len(holdout):
            verdict = "the capability survived the unseen holdout"
        elif not holdout:
            verdict = "no holdout: generalization is unknown"
        else:
            verdict = "not sufficient evidence of generalization"
        return GeneralizationReport(tp, len(train), hp, len(holdout),
                                    list(variation_axes or []), failures,
                                    verdict, overfit)


@dataclass
class ReconstructionPlan:
    available: list[str]
    can_reconstruct: list[str]
    underdetermined: list[str]
    missing_evidence: list[str]
    steps: list[str]
    confidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceReconstructor:
    """Plan a reconstruction from heterogeneous evidence, without pretending.

    Multiple implementations can explain the same observations. The planner
    names that underdetermination instead of choosing the most convenient story.
    """

    SIGNALS = ("executable", "screenshots", "logs", "api_traces",
               "documentation", "behavior_examples", "source", "interviews")

    def plan(self, evidence: dict[str, Any]) -> ReconstructionPlan:
        available = [k for k in self.SIGNALS if evidence.get(k)]
        can = []
        if evidence.get("source"):
            can.append("source-level restoration")
        if evidence.get("executable"):
            can.append("observable behavior and structure")
        if evidence.get("behavior_examples"):
            can.append("acceptance tests for the requested scope")
        if evidence.get("api_traces"):
            can.append("interface contracts for observed calls")
        missing = [k for k in self.SIGNALS if not evidence.get(k)]
        underdetermined = []
        if not evidence.get("source"):
            underdetermined.append("internal algorithms and data structures")
        if not evidence.get("documentation"):
            underdetermined.append("intended semantics beyond observed cases")
        if not evidence.get("interviews"):
            underdetermined.append("business rules and historical decisions")
        steps = [
            "record concrete observations with hashes and timestamps",
            "build a world model of components and interfaces",
            "write acceptance tests for the requested behavior",
            "implement the smallest replacement that passes them",
            "run differential tests against the evidence",
            "report what is verified, what is inferred, and what is unknown",
        ]
        return ReconstructionPlan(
            available, can, underdetermined, missing, steps,
            "observed" if evidence.get("behavior_examples") else "hypothesis")


class RepresentationSearch:
    def choose(self, candidates: list[dict[str, Any]],
               benchmark: Callable[[str], dict[str, float]]) -> dict[str, Any]:
        rows = []
        for c in candidates:
            try:
                metrics = benchmark(str(c.get("name")))
            except Exception as exc:
                rows.append({"candidate": c.get("name"), "error": str(exc)})
                continue
            rows.append({"candidate": c.get("name"), "metrics": metrics})
        ok = [r for r in rows if "metrics" in r]
        if not ok:
            return {"choice": None, "reason": "no representation could be benchmarked",
                    "rows": rows}
        best = max(ok, key=lambda r: sum(r["metrics"].values()))
        return {"choice": best["candidate"], "rows": rows,
                "note": "a benchmark on representative cases, not a universal proof"}
