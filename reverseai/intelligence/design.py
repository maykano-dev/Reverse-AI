"""Architecture search and measured algorithm optimization.

The important capability is not "generate ten designs." It is rejecting designs
that do not satisfy the constraints, measuring the survivors, and showing the
trade-off. The benchmark callback is injected; in production it must run target
code in the sandbox.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

BenchmarkFn = Callable[[str, dict[str, Any]], dict[str, Any]]


@dataclass
class Objective:
    name: str
    weight: float = 1.0
    direction: str = "max"       # max | min
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Candidate:
    id: str
    name: str
    description: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    measurements: dict[str, float] = field(default_factory=dict)
    risk: int = 2
    complexity: int = 2
    cost: float = 0.0
    evidence: list[str] = field(default_factory=list)
    constraints_met: bool = True
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArchitectureReport:
    candidates: list[Candidate]
    objectives: list[Objective]
    scores: dict[str, float]
    pareto: list[str]
    recommendation: str
    tradeoffs: list[str]
    unmeasured: list[str]
    confidence: str = "hypothesis"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [c.to_dict() for c in self.candidates],
            "objectives": [o.to_dict() for o in self.objectives],
            "scores": self.scores, "pareto": self.pareto,
            "recommendation": self.recommendation,
            "tradeoffs": self.tradeoffs, "unmeasured": self.unmeasured,
            "confidence": self.confidence,
        }


def _normalize(value: float, values: list[float], direction: str) -> float:
    lo, hi = min(values), max(values)
    if hi == lo:
        return 1.0
    x = (value - lo) / (hi - lo)
    return x if direction == "max" else 1.0 - x


def score_candidates(candidates: list[Candidate],
                     objectives: list[Objective]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for obj in objectives:
        values = [c.measurements.get(obj.name, 0.0) for c in candidates]
        if not any(obj.name in c.measurements for c in candidates):
            continue
        for c in candidates:
            if obj.name not in c.measurements:
                continue
            scores[c.id] = scores.get(c.id, 0.0) + (
                obj.weight * _normalize(c.measurements[obj.name], values,
                                        obj.direction))
    total = sum(max(0.0, o.weight) for o in objectives) or 1.0
    for cid in list(scores):
        scores[cid] = round(scores[cid] / total, 4)
    return scores


def pareto_front(candidates: list[Candidate],
                 objectives: list[Objective]) -> list[str]:
    measurable = [o for o in objectives
                  if any(o.name in c.measurements for c in candidates)]
    front = []
    for c in candidates:
        dominated = False
        for other in candidates:
            if other.id == c.id:
                continue
            better_or_equal = True
            strictly_better = False
            for obj in measurable:
                if obj.name not in c.measurements or obj.name not in other.measurements:
                    continue
                a = c.measurements[obj.name]
                b = other.measurements[obj.name]
                good = b >= a if obj.direction == "max" else b <= a
                strict = b > a if obj.direction == "max" else b < a
                if not good:
                    better_or_equal = False
                    break
                if strict:
                    strictly_better = True
            if better_or_equal and strictly_better:
                dominated = True
                break
        if not dominated:
            front.append(c.id)
    return front


class ArchitectureSearch:
    def search(self, candidates: list[Candidate], objectives: list[Objective],
               *, constraints: list[str] | None = None) -> ArchitectureReport:
        constraints = constraints or []
        for c in candidates:
            c.violations = [x for x in constraints
                            if c.attributes.get(x) is False]
            c.constraints_met = not c.violations
        viable = [c for c in candidates if c.constraints_met]
        scores = score_candidates(viable, objectives)
        front = pareto_front(viable, objectives)
        unmeasured = [o.name for o in objectives
                      if not any(o.name in c.measurements for c in viable)]
        ranked = sorted(viable, key=lambda c: scores.get(c.id, 0.0), reverse=True)
        recommendation = ""
        tradeoffs = []
        if ranked:
            best = ranked[0]
            recommendation = (f"{best.name} has the best weighted score "
                              f"({scores.get(best.id, 0):.3f}) among feasible candidates.")
            for other in ranked[1:5]:
                tradeoffs.append(
                    f"{other.name}: score {scores.get(other.id, 0):.3f}, "
                    f"risk {other.risk}, complexity {other.complexity}, "
                    f"cost {other.cost}")
        else:
            recommendation = "No candidate satisfies the stated constraints."
        confidence = "observed" if not unmeasured and viable else "hypothesis"
        return ArchitectureReport(viable, objectives, scores, front,
                                  recommendation, tradeoffs, unmeasured,
                                  confidence)

    def benchmark(self, candidate: Candidate, fn: BenchmarkFn,
                  cases: list[dict[str, Any]]) -> Candidate:
        measurements = dict(candidate.measurements)
        for i, case in enumerate(cases):
            try:
                out = fn(candidate.name, dict(case))
                for key, value in (out or {}).items():
                    if isinstance(value, (int, float)):
                        measurements.setdefault(key, 0.0)
                        measurements[key] += float(value)
            except Exception as exc:
                candidate.violations.append(
                    f"benchmark case {i} failed: {type(exc).__name__}: {exc}")
        candidate.measurements = measurements
        candidate.constraints_met = not candidate.violations
        candidate.evidence.append(f"benchmarked {len(cases)} case(s)")
        return candidate


@dataclass
class BenchmarkCase:
    name: str
    inputs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AlgorithmComparison:
    baseline: str
    candidate: str
    baseline_metrics: dict[str, float] = field(default_factory=dict)
    candidate_metrics: dict[str, float] = field(default_factory=dict)
    speedup: float | None = None
    memory_change: float | None = None
    equivalent: bool | None = None
    cases: int = 0
    failures: list[str] = field(default_factory=list)
    improvement: str = ""
    confidence: str = "hypothesis"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AlgorithmOptimizer:
    def __init__(self) -> None:
        self.baseline_path = ""
        self.candidate_path = ""

    def compare(self, baseline: str, candidate: str, cases: list[dict[str, Any]],
                fn: Callable[[str, dict[str, Any]], dict[str, Any]]) -> AlgorithmComparison:
        base: dict[str, float] = {}
        cand: dict[str, float] = {}
        failures: list[str] = []
        equivalent = True
        for i, case in enumerate(cases):
            try:
                a = fn(baseline, dict(case))
                b = fn(candidate, dict(case))
            except Exception as exc:
                failures.append(f"case {i}: {type(exc).__name__}: {exc}")
                continue
            if "output" in a or "output" in b:
                if a.get("output") != b.get("output"):
                    equivalent = False
            for key, value in (a or {}).items():
                if isinstance(value, (int, float)):
                    base[key] = base.get(key, 0.0) + float(value)
            for key, value in (b or {}).items():
                if isinstance(value, (int, float)):
                    cand[key] = cand.get(key, 0.0) + float(value)
        speedup = None
        if base.get("seconds") and cand.get("seconds"):
            speedup = round(base["seconds"] / cand["seconds"], 3)
        memory_change = None
        if base.get("peak_bytes") and cand.get("peak_bytes"):
            memory_change = round(
                (cand["peak_bytes"] - base["peak_bytes"]) / base["peak_bytes"], 4)
        if failures:
            confidence = "unknown"
        elif equivalent and speedup is not None:
            confidence = "observed"
        else:
            confidence = "hypothesis"
        improvement = (
            f"{speedup:.2f}x faster" if speedup and speedup > 1
            else "no measured speedup" if speedup else "no timing measurement")
        return AlgorithmComparison(
            baseline, candidate, base, cand, speedup, memory_change,
            equivalent, len(cases), failures, improvement, confidence)
