"""Evidence tracking with explicit confidence tiers.

The platform's credibility rests on never confusing a guess with a fact. Every
finding the agent records carries a confidence tier and, ideally, a pointer to
how it was established (which tool, which observation).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any


class Confidence(IntEnum):
    """How strongly a claim is supported.

    BELIEVED  — model inference / hypothesis, not yet checked against evidence.
    OBSERVED  — directly read from the artifact or a tool's deterministic output.
    VERIFIED  — demonstrated by execution/testing in the sandbox.
    """

    BELIEVED = 1
    OBSERVED = 2
    VERIFIED = 3

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass
class Finding:
    claim: str
    confidence: Confidence
    source: str = ""          # tool name or reasoning step that produced it
    detail: str = ""
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["confidence"] = self.confidence.label
        return d


class EvidenceLog:
    """Ordered collection of findings with confidence-aware querying."""

    def __init__(self) -> None:
        self._findings: list[Finding] = []

    def add(
        self,
        claim: str,
        confidence: Confidence,
        source: str = "",
        detail: str = "",
    ) -> Finding:
        f = Finding(claim=claim, confidence=confidence, source=source, detail=detail)
        self._findings.append(f)
        return f

    def believed(self, claim: str, **kw: Any) -> Finding:
        return self.add(claim, Confidence.BELIEVED, **kw)

    def observed(self, claim: str, **kw: Any) -> Finding:
        return self.add(claim, Confidence.OBSERVED, **kw)

    def verified(self, claim: str, **kw: Any) -> Finding:
        return self.add(claim, Confidence.VERIFIED, **kw)

    def all(self) -> list[Finding]:
        return list(self._findings)

    def at_least(self, confidence: Confidence) -> list[Finding]:
        return [f for f in self._findings if f.confidence >= confidence]

    def to_list(self) -> list[dict[str, Any]]:
        return [f.to_dict() for f in self._findings]

    def summary(self) -> dict[str, int]:
        counts = {c.label: 0 for c in Confidence}
        for f in self._findings:
            counts[f.confidence.label] += 1
        return counts
