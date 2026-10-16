"""Job record — the durable, inspectable unit of work.

A Job captures everything about one investigation: the goal, the target, the
full message transcript, every tool call (via the audit log), the evidence
gathered at each confidence tier, and the final outcome. This is what makes
runs resumable, comparable, and — later — usable as training data.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .evidence import EvidenceLog


def _job_id() -> str:
    return f"job_{uuid.uuid4().hex[:12]}"


@dataclass
class Job:
    goal: str
    target_path: str | None = None
    id: str = field(default_factory=_job_id)
    workspace: str = ""
    status: str = "created"   # created|running|completed|failed|refused
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    evidence: EvidenceLog = field(default_factory=EvidenceLog)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    audit: list[dict[str, Any]] = field(default_factory=list)
    steps: int = 0
    final_answer: str = ""
    error: str | None = None
    usage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "target_path": self.target_path,
            "workspace": self.workspace,
            "status": self.status,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "steps": self.steps,
            "final_answer": self.final_answer,
            "error": self.error,
            "usage": self.usage,
            "evidence": self.evidence.to_list(),
            "evidence_summary": self.evidence.summary(),
            "audit": self.audit,
            "transcript": self.transcript,
        }

    def save(self, directory: str | Path) -> Path:
        d = Path(directory)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{self.id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path

    def report(self) -> str:
        """Human-readable summary that respects confidence tiers."""
        lines = [
            f"ReverseAI job {self.id}",
            f"status: {self.status}  steps: {self.steps}",
            f"goal: {self.goal}",
            f"target: {self.target_path or '(none)'}",
            "",
            "Evidence (by confidence):",
        ]
        from .evidence import Confidence

        for tier in (Confidence.VERIFIED, Confidence.OBSERVED, Confidence.BELIEVED):
            items = [f for f in self.evidence.all() if f.confidence == tier]
            if items:
                lines.append(f"  [{tier.label}]")
                for f in items:
                    lines.append(f"    - {f.claim}")
        if self.error:
            lines += ["", f"error: {self.error}"]
        lines += ["", "Conclusion:", self.final_answer or "(none)"]
        return "\n".join(lines)
