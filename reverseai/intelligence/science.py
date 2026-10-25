"""Hypothesis-driven experimentation.

A claim is not a conclusion just because a model stated it. This module makes the
scientific loop explicit:

    hypothesis -> experiment design -> prediction -> observation -> update

The runner is injected by the caller. In production it must be a sandbox-backed
callable; this module never executes target code itself.

The evidence vocabulary is deliberately small:

  established  repeated, independent observation with a stated scope
  observed     one controlled observation
  hypothesis   a plausible explanation that has not been tested
  unknown      not enough evidence to choose
"""

from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

LABELS = ("established", "observed", "hypothesis", "unknown")
Prediction = dict[str, Any]
Runner = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class Hypothesis:
    id: str
    statement: str
    predicts: Prediction = field(default_factory=dict)
    status: str = "untested"        # untested | supported | challenged | refuted
    confidence: str = "hypothesis"
    evidence: list[dict[str, Any]] = field(default_factory=list)
    experiment_ids: list[str] = field(default_factory=list)
    scope: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ExperimentCase:
    name: str
    inputs: dict[str, Any] = field(default_factory=dict)
    prediction: Prediction = field(default_factory=dict)
    observed: dict[str, Any] = field(default_factory=dict)
    matched: bool | None = None
    error: str = ""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Experiment:
    id: str
    hypothesis_id: str
    variable: str
    control: dict[str, Any] = field(default_factory=dict)
    cases: list[ExperimentCase] = field(default_factory=list)
    status: str = "designed"        # designed | ran | failed
    summary: str = ""
    prediction: Prediction = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "hypothesis_id": self.hypothesis_id,
            "variable": self.variable, "control": self.control,
            "cases": [c.to_dict() for c in self.cases],
            "status": self.status, "summary": self.summary,
            "prediction": self.prediction,
        }


@dataclass
class ExperimentResult:
    experiment: Experiment
    matched: int = 0
    mismatched: int = 0
    errors: int = 0
    confidence: str = "unknown"
    supported: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment.to_dict(),
            "matched": self.matched, "mismatched": self.mismatched,
            "errors": self.errors, "confidence": self.confidence,
            "supported": self.supported, "reason": self.reason,
        }


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def compare_prediction(prediction: Prediction, observed: dict[str, Any]) -> tuple[bool, list[str]]:
    """Compare only the keys the hypothesis predicted; unexpected keys are data."""
    notes: list[str] = []
    if not prediction:
        return False, ["the hypothesis made no testable prediction"]
    ok = True
    for key, want in prediction.items():
        got = observed.get(key, _MISSING)
        if got is _MISSING:
            ok = False
            notes.append(f"missing observed key: {key}")
        elif isinstance(want, (int, float)) and isinstance(got, (int, float)):
            # exact numeric equality; tolerance is an experiment's explicit job
            if want != got:
                ok = False
                notes.append(f"{key}: predicted {want!r}, observed {got!r}")
        elif want != got:
            ok = False
            notes.append(f"{key}: predicted {want!r}, observed {got!r}")
    return ok, notes


_MISSING = object()


class ExperimentEngine:
    def __init__(self) -> None:
        self.hypotheses: dict[str, Hypothesis] = {}
        self.experiments: dict[str, Experiment] = {}

    def hypothesize(self, statement: str, predicts: Prediction | None = None,
                    *, scope: str = "") -> Hypothesis:
        h = Hypothesis(_id("hyp"), statement[:4000], dict(predicts or {}),
                       scope=scope[:500])
        self.hypotheses[h.id] = h
        return h

    def design(self, hypothesis_id: str, variable: str,
               cases: Iterable[dict[str, Any]],
               *, control: dict[str, Any] | None = None,
               prediction: Prediction | None = None) -> Experiment:
        if hypothesis_id not in self.hypotheses:
            raise ValueError("unknown hypothesis")
        exp = Experiment(_id("exp"), hypothesis_id, variable[:120],
                         dict(control or {}),
                         [ExperimentCase(
                             str(c.get("name") or f"case-{i + 1}"),
                             dict(c.get("inputs") or c.get("args") or {}),
                             dict(c.get("prediction") or prediction or {}))
                          for i, c in enumerate(cases)],
                         prediction=dict(prediction or {}))
        if not exp.cases:
            raise ValueError("an experiment needs at least one case")
        self.experiments[exp.id] = exp
        self.hypotheses[hypothesis_id].experiment_ids.append(exp.id)
        return exp

    def run(self, experiment_id: str, runner: Runner) -> ExperimentResult:
        exp = self.experiments.get(experiment_id)
        if exp is None:
            raise ValueError("unknown experiment")
        h = self.hypotheses[exp.hypothesis_id]
        matched = mismatched = errors = 0
        for case in exp.cases:
            try:
                observed = runner(dict(case.inputs))
                if not isinstance(observed, dict):
                    raise TypeError("runner must return a mapping")
                case.observed = observed
                ok, notes = compare_prediction(case.prediction or exp.prediction,
                                               observed)
                case.matched = ok
                case.notes = notes
                if ok:
                    matched += 1
                else:
                    mismatched += 1
                    h.status = "challenged" if h.status == "untested" else h.status
            except Exception as exc:  # runner/environment failure, not evidence
                errors += 1
                case.error = f"{type(exc).__name__}: {exc}"
        ran = matched + mismatched
        exp.status = "ran" if ran else "failed"
        if matched and not mismatched:
            h.status = "supported"
            h.confidence = "observed"
        elif mismatched and not matched:
            h.status = "refuted"
            h.confidence = "observed"
        elif mismatched and matched:
            h.status = "challenged"
            h.confidence = "observed"
        h.evidence.append({
            "experiment_id": exp.id, "matched": matched,
            "mismatched": mismatched, "errors": errors,
        })
        if matched + mismatched >= 2 and matched >= 2 and not mismatched:
            h.confidence = "established" if matched >= 3 else "observed"
        exp.summary = (f"{matched} matched, {mismatched} mismatched, "
                       f"{errors} environment error(s)")
        result = ExperimentResult(
            exp, matched, mismatched, errors, h.confidence,
            supported=bool(matched and not mismatched),
            reason=exp.summary)
        return result

    def review(self) -> list[dict[str, Any]]:
        """Adversarial review notes, not a vote."""
        out = []
        for h in self.hypotheses.values():
            notes = []
            if h.status == "untested":
                notes.append("no experiment has run")
            if h.status == "supported" and len(h.experiment_ids) < 2:
                notes.append("only one experiment supports this; reproduce it")
            if h.status == "refuted":
                notes.append("at least one prediction failed; update the model")
            if not h.predicts and not any(self.experiments[i].prediction
                                          for i in h.experiment_ids):
                notes.append("no falsifiable prediction")
            if notes:
                out.append({"hypothesis": h.to_dict(), "review": notes})
        return out

    def discriminating_case(self, hypothesis_ids: list[str],
                            candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """Pick the case whose predicted outcomes differ most across hypotheses.

        This is a bounded heuristic, not a proof of information gain. It exists
        so the agent tests a distinction instead of asking for another opinion.
        """
        hyps = [self.hypotheses[i] for i in hypothesis_ids if i in self.hypotheses]
        best = None
        best_score = -1.0
        for case in candidates:
            values = []
            for h in hyps:
                values.append(str(h.predicts.get(case.get("key"), "<unset>")))
            distinct = len(set(values))
            score = distinct / max(1, len(hyps))
            if score > best_score:
                best, best_score = case, score
        return {"case": best, "score": round(max(best_score, 0), 3),
                "note": "distinct predictions, not a probability"}

    def summary(self) -> dict[str, Any]:
        statuses: dict[str, int] = {}
        for h in self.hypotheses.values():
            statuses[h.status] = statuses.get(h.status, 0) + 1
        return {
            "hypotheses": len(self.hypotheses),
            "experiments": len(self.experiments),
            "statuses": statuses,
            "needs_review": len(self.review()),
        }


EVIDENCE_CLASSES = ("prediction", "simulation", "observation", "unknown")


@dataclass
class RealityClaim:
    claim: str
    kind: str             # prediction | simulation | observation | unknown
    source: str = ""
    detail: str = ""
    scope: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RealityEngine:
    """Keep model predictions, simulations, and observations distinct."""

    def __init__(self) -> None:
        self.claims: list[RealityClaim] = []

    def add(self, claim: str, kind: str, *, source: str = "", detail: str = "",
            scope: str = "") -> RealityClaim:
        if kind not in EVIDENCE_CLASSES:
            raise ValueError(f"unknown evidence class: {kind}")
        c = RealityClaim(claim[:4000], kind, source[:200], detail[:4000],
                         scope[:500])
        self.claims.append(c)
        return c

    def summary(self) -> dict[str, Any]:
        counts = {k: 0 for k in EVIDENCE_CLASSES}
        for c in self.claims:
            counts[c.kind] += 1
        return {
            "counts": counts,
            "strongest": ("observation" if counts["observation"] else
                          "simulation" if counts["simulation"] else
                          "prediction" if counts["prediction"] else "unknown"),
            "note": "a simulation is not an observation; a prediction is not a fact",
        }


def hypothesis_from_opportunity(opportunity: dict[str, Any]) -> Hypothesis:
    """Turn an opportunity into a falsifiable claim, with an explicit prediction."""
    title = str(opportunity.get("title") or "untitled opportunity")
    predicts = dict(opportunity.get("predicts") or {})
    if not predicts:
        predicts = {"changes_behavior": True} if "unlock" in title.lower() else {}
    return Hypothesis(_id("hyp"), f"{title} is worth acting on", predicts,
                      scope=str(opportunity.get("evidence", ""))[:500])
