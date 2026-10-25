"""Build a dataset only from verified engineering traces.

A job is eligible only when the verification tier is verified and delivery was
allowed. Unverified or blocked jobs are not training data. Secrets are redacted
before export, and the split is deterministic so a holdout cannot silently move.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[^\s,;]{8,}"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
)


class DatasetError(Exception):
    pass


def redact(text: str) -> str:
    out = text
    for pat in SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


@dataclass
class TraceRecord:
    job_id: str
    goal: str
    target: str
    mode: str = ""
    strategy: str = ""
    verification: dict[str, Any] = field(default_factory=dict)
    delivery: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    artifact_sha256: str = ""
    cost_usd: float = 0.0
    created_at: float = 0.0
    split: str = "train"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TraceDataset:
    records: list[TraceRecord] = field(default_factory=list)
    rejected: int = 0
    duplicates: int = 0
    redactions: int = 0

    def by_split(self) -> dict[str, list[TraceRecord]]:
        return {
            "train": [r for r in self.records if r.split == "train"],
            "holdout": [r for r in self.records if r.split == "holdout"],
        }

    def summary(self) -> dict[str, Any]:
        splits = self.by_split()
        return {
            "records": len(self.records),
            "train": len(splits["train"]),
            "holdout": len(splits["holdout"]),
            "rejected_unverified": self.rejected,
            "duplicates": self.duplicates,
            "redactions": self.redactions,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"summary": self.summary(),
                "records": [r.to_dict() for r in self.records]}

    def export_jsonl(self, path: str | os.PathLike) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as fh:
            for record in self.records:
                fh.write(json.dumps(record.to_dict()) + "\n")
        return p


def _eligible(job: dict[str, Any]) -> bool:
    verification = job.get("verification") or {}
    delivery = job.get("delivery") or {}
    return bool(verification.get("verified")) and bool(delivery.get("allowed"))


def _trace(job: dict[str, Any], split: str) -> TraceRecord:
    verification = job.get("verification") or {}
    delivery = job.get("delivery") or {}
    artifact = (job.get("artifact_meta") or {}).get("sha256") or ""
    goal = redact(str(job.get("goal") or ""))[:4000]
    target = redact(str(job.get("target_path") or ""))[:1000]
    # Keep the verified evidence and the strategy, not the whole transcript.
    evidence = []
    for row in job.get("evidence") or []:
        evidence.append({
            "claim": redact(str(row.get("claim") or ""))[:1000],
            "confidence": row.get("confidence", ""),
            "source": row.get("source", ""),
            "detail": redact(str(row.get("detail") or ""))[:2000],
        })
    return TraceRecord(
        job_id=str(job.get("id") or ""),
        goal=goal, target=target, mode=str(job.get("mode") or ""),
        strategy=str((job.get("modification_plan") or {}).get("strategy") or ""),
        verification={"verified": True, "passed_tests": verification.get("passed_tests"),
                      "tests_run": verification.get("tests_run"),
                      "reason": redact(str(verification.get("reason") or ""))[:1000]},
        delivery={"allowed": True, "reason": redact(str(delivery.get("reason") or ""))[:1000]},
        evidence=evidence,
        opportunities=list(job.get("opportunities") or [])[:20],
        hypotheses=list(job.get("hypotheses") or [])[:20],
        artifact_sha256=artifact,
        cost_usd=float((job.get("usage") or {}).get("cost_usd") or 0),
        created_at=float(job.get("created_at") or 0),
        split=split,
    )


def _split(job: dict[str, Any], holdout_percent: int = 20) -> str:
    seed = str(job.get("id") or "") + "|" + str(job.get("goal") or "")
    value = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % 100
    return "holdout" if value < max(0, min(100, holdout_percent)) else "train"


def extract_traces(store_dir: str | os.PathLike, *,
                   holdout_percent: int = 20,
                   require_verified: bool = True) -> TraceDataset:
    root = Path(store_dir)
    dataset = TraceDataset()
    seen: set[str] = set()
    for path in sorted(root.glob("job_*.json")):
        try:
            job = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if require_verified and not _eligible(job):
            dataset.rejected += 1
            continue
        key = (job.get("artifact_meta") or {}).get("sha256") or job.get("id")
        if key in seen:
            dataset.duplicates += 1
            continue
        seen.add(str(key))
        split = _split(job, holdout_percent)
        record = _trace(job, split)
        if any(p.search(record.goal + record.target)
               for p in SECRET_PATTERNS):
            dataset.redactions += 1
        dataset.records.append(record)
    return dataset
