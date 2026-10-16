"""Job store — persist, list, and retrieve Job records on disk.

Each job is one JSON file. This is the durable record behind the API and the
seed corpus for future training-data collection (verified investigation traces).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .job import Job


class JobStore:
    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, job: Job) -> Path:
        return job.save(self.dir)

    def path_for(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.json"

    def get(self, job_id: str) -> dict[str, Any] | None:
        # job_id is validated to be a bare identifier to prevent traversal.
        if not _safe_id(job_id):
            return None
        p = self.path_for(job_id)
        if not p.is_file():
            return None
        try:
            return json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def list_summaries(self, limit: int = 100) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        files = sorted(self.dir.glob("job_*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for p in files[:limit]:
            try:
                d = json.loads(p.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            out.append({
                "id": d.get("id"),
                "goal": d.get("goal"),
                "status": d.get("status"),
                "steps": d.get("steps"),
                "created_at": d.get("created_at"),
                "evidence_summary": d.get("evidence_summary"),
            })
        return out


def _safe_id(job_id: str) -> bool:
    return (
        isinstance(job_id, str)
        and job_id.startswith("job_")
        and job_id[4:].isalnum()
        and len(job_id) <= 40
    )
