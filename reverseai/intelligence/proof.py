"""Proof-carrying artifacts, independent verification, calibration, regressions.

The modifier and the verifier are different roles. This module builds a package
that the verifier can check without trusting the modifier's narrative, and it
refuses to turn a small sample into a confident percentage.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..verify.difftest import DiffReport, InputCase, run_differential
from ..verify.report import build_report, render_json, verify_signature
from ..verify.corpus import CorpusStore, target_sha256


def _sha(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


@dataclass
class ArtifactRef:
    name: str
    path: str
    sha256: str
    size: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProofPackage:
    id: str
    goal: str
    original: ArtifactRef
    modified: ArtifactRef | None
    change: str = ""
    tools: list[str] = field(default_factory=list)
    versions: dict[str, str] = field(default_factory=dict)
    tests: list[dict[str, Any]] = field(default_factory=list)
    measurements: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    reproduction: list[str] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "goal": self.goal,
            "original": self.original.to_dict(),
            "modified": self.modified.to_dict() if self.modified else None,
            "change": self.change, "tools": self.tools,
            "versions": self.versions, "tests": self.tests,
            "measurements": self.measurements,
            "limitations": self.limitations,
            "reproduction": self.reproduction,
            "report": self.report, "created_at": self.created_at,
        }

    def save(self, directory: str) -> dict[str, str]:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        manifest = d / "proof.json"
        manifest.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        markdown = d / "PROOF.md"
        lines = [
            f"# Proof package {self.id}", "",
            f"**Goal:** {self.goal}", "",
            f"**Original:** `{self.original.name}`  ",
            f"`{self.original.sha256}`", "",
        ]
        if self.modified:
            lines += [f"**Modified:** `{self.modified.name}`  ",
                      f"`{self.modified.sha256}`", ""]
        lines += [f"**Change:** {self.change}", "", "## Tests", ""]
        lines += [f"- {t.get('name')}: {t.get('result')}" for t in self.tests] or ["- none"]
        lines += ["", "## Measurements", ""]
        lines += [f"- {k}: {v}" for k, v in self.measurements.items()] or ["- none"]
        lines += ["", "## Limitations", ""]
        lines += [f"- {x}" for x in self.limitations] or ["- none recorded"]
        lines += ["", "## Reproduce", "", "```bash"]
        lines += self.reproduction or ["# no replay command was recorded"]
        lines += ["```", "", "## Signature", "",
                  f"{self.report.get('algorithm', '')}",
                  f"`{self.report.get('signature', '')}`", ""]
        markdown.write_text("\n".join(lines), encoding="utf-8")
        return {"manifest": str(manifest), "markdown": str(markdown)}


def build_proof_package(goal: str, original: str, modified: str | None, *,
                        change: str = "", tools: list[str] | None = None,
                        versions: dict[str, str] | None = None,
                        tests: list[dict[str, Any]] | None = None,
                        measurements: dict[str, Any] | None = None,
                        limitations: list[str] | None = None,
                        record: dict[str, Any] | None = None,
                        report: dict[str, Any] | None = None) -> ProofPackage:
    report = report or (build_report(record) if record else {})
    orig = ArtifactRef(Path(original).name, str(original), _sha(original),
                       Path(original).stat().st_size
                       if Path(original).is_file() else None)
    mod = None
    if modified:
        mod = ArtifactRef(Path(modified).name, str(modified), _sha(modified),
                          Path(modified).stat().st_size
                          if Path(modified).is_file() else None)
    replay = (report.get("replay") or {}).get("command") if report else ""
    return ProofPackage(
        f"proof_{uuid.uuid4().hex[:10]}", goal, orig, mod, change,
        list(tools or []), dict(versions or {}), list(tests or []),
        dict(measurements or {}),
        list(limitations or []) + [
            "verification covers the declared cases, not every input",
            "a signature proves integrity, not truth",
        ],
        [replay] if replay else [], report)


# ---------------------------------------------------------------------------
# Independent verification
# ---------------------------------------------------------------------------

@dataclass
class IndependentResult:
    verified: bool
    reason: str
    report: dict[str, Any] = field(default_factory=dict)
    prohibited: list[str] = field(default_factory=list)
    acceptance: list[dict[str, Any]] = field(default_factory=list)
    signature_valid: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IndependentVerifier:
    """Run the declared cases without trusting the modifier's claims."""

    def __init__(self, cases: list[InputCase], *,
                 prohibited_changes: list[str] | None = None) -> None:
        self.cases = cases
        self.prohibited_changes = list(prohibited_changes or [])

    def _prohibited(self, original: str, modified: str) -> list[str]:
        out = []
        for name in self.prohibited_changes:
            a = Path(original).parent / name
            b = Path(modified).parent / name
            if a.exists() and b.exists() and _sha(str(a)) != _sha(str(b)):
                out.append(f"prohibited file changed: {name}")
            if a.exists() != b.exists():
                out.append(f"prohibited file added/removed: {name}")
        return out

    def verify(self, original: str, modified: str, *,
               policy=None, acceptance: list[Callable[[dict[str, Any]], bool]] | None = None,
               report: dict[str, Any] | None = None) -> IndependentResult:
        diff: DiffReport = run_differential(original, modified, self.cases,
                                            policy=policy)
        failure = self._prohibited(original, modified)
        accepts = []
        for i, fn in enumerate(acceptance or []):
            try:
                ok = bool(fn({"diff": diff.to_dict(), "original": original,
                              "modified": modified}))
            except Exception as exc:
                ok = False
                accepts.append({"index": i, "ok": False,
                                "error": f"{type(exc).__name__}: {exc}"})
                continue
            accepts.append({"index": i, "ok": ok})
        expected = [c for c in diff.cases if c.expected_met is not None]
        verified = bool(diff.ran and expected and
                        all(c.expected_met for c in expected) and
                        not diff.unexpected and not failure and
                        all(a["ok"] for a in accepts))
        reason = ("independent verification passed"
                  if verified else
                  "independent verification failed: " + "; ".join(
                      ([f"unexpected: {', '.join(diff.unexpected)}"] if diff.unexpected else [])
                      + ([f"expectation failed: {', '.join(diff.failed_expectations)}"]
                         if diff.failed_expectations else [])
                      + failure
                      + ([a.get("error", "acceptance check failed")
                          for a in accepts if not a["ok"]]) or ["no evidence"]))
        return IndependentResult(verified, reason, diff.to_dict(), failure, accepts,
                                 verify_signature(report) if report else None)


# ---------------------------------------------------------------------------
# Confidence calibration
# ---------------------------------------------------------------------------

@dataclass
class CalibrationBin:
    label: str
    predicted: float
    samples: int = 0
    correct: int = 0

    @property
    def observed(self) -> float | None:
        return round(self.correct / self.samples, 3) if self.samples else None


class ConfidenceCalibrator:
    """Only report a numeric confidence after real outcomes support it."""

    def __init__(self, min_samples: int = 10) -> None:
        self.min_samples = min_samples
        self.outcomes: list[tuple[float, bool]] = []

    def record(self, predicted: float, correct: bool) -> None:
        self.outcomes.append((min(max(float(predicted), 0.0), 1.0), bool(correct)))

    def bins(self) -> list[dict[str, Any]]:
        buckets: dict[int, CalibrationBin] = {}
        for p, ok in self.outcomes:
            idx = min(9, int(p * 10))
            b = buckets.setdefault(idx, CalibrationBin(f"{idx * 10}-{idx * 10 + 10}%",
                                                       (idx + 0.5) / 10))
            b.samples += 1
            b.correct += 1 if ok else 0
        return [{"label": b.label, "predicted": b.predicted,
                 "samples": b.samples, "observed": b.observed}
                for _, b in sorted(buckets.items())]

    def report(self) -> dict[str, Any]:
        return {
            "samples": len(self.outcomes),
            "bins": self.bins(),
            "published": len(self.outcomes) >= self.min_samples,
            "note": ("no numeric confidence is published below the minimum "
                     "sample size; use a qualitative label instead"),
        }

    def label(self, predicted: float) -> str:
        if len(self.outcomes) < self.min_samples:
            return "uncalibrated"
        idx = min(9, int(min(max(predicted, 0.0), 1.0) * 10))
        rows = [b for b in self.bins() if b["label"].startswith(str(idx * 10))]
        if not rows or rows[0]["observed"] is None:
            return "uncalibrated"
        observed = rows[0]["observed"]
        if observed >= 0.8:
            return "strongly supported"
        if observed >= 0.5:
            return "tentative"
        return "weak"


# ---------------------------------------------------------------------------
# Regression promotion
# ---------------------------------------------------------------------------

def promote_regression(store: CorpusStore, target: str,
                       case: InputCase, *, goal: str = "") -> dict[str, Any]:
    """Add one confirmed case to the durable corpus, preserving prior cases."""
    sha = target_sha256(target)
    existing = store.load(sha)
    if any(c.name == case.name for c in existing):
        existing = [c for c in existing if c.name != case.name]
    existing.append(case.normalized())
    path = store.save(sha, existing, goal=goal or "promoted regression")
    return {"target_sha256": sha, "cases": len(existing), "path": str(path)}
