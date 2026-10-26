"""Job store — persist, list, and retrieve Job records on disk.

Each job is one JSON file. This is the durable record behind the API and the
seed corpus for future training-data collection (verified investigation traces).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .job import Job


class JobStore:
    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_dir = self.dir / "events"
        self.conversations_dir = self.dir / "conversations"
        self.workspaces_dir = self.dir / "workspaces"
        for d in (self.events_dir, self.conversations_dir, self.workspaces_dir):
            d.mkdir(parents=True, exist_ok=True)

    def save(self, job: Job) -> Path:
        return job.save(self.dir)

    def path_for(self, job_id: str) -> Path:
        return self.dir / f"{job_id}.json"

    def save_artifact(self, job_id: str, src_path: str) -> str | None:
        """Copy a delivered file into durable storage keyed by job id."""
        import shutil

        if not _safe_id(job_id):
            return None
        src = Path(src_path)
        if not src.is_file():
            return None
        adir = self.dir / "artifacts"
        adir.mkdir(parents=True, exist_ok=True)
        name = Path(src_path).name
        dest = adir / f"{job_id}__{name}"
        try:
            shutil.copy2(src, dest)
        except OSError:
            return None
        return str(dest)

    def delete(self, job_id: str) -> bool:
        """Delete a stored job and any artifact it produced."""
        if not _safe_id(job_id):
            return False
        removed = False
        p = self.path_for(job_id)
        if p.is_file():
            try:
                p.unlink()
                removed = True
            except OSError:
                pass
        art = self.artifact_for(job_id)
        if art:
            try:
                art.unlink()
            except OSError:
                pass
        return removed

    def artifact_for(self, job_id: str) -> Path | None:
        if not _safe_id(job_id):
            return None
        adir = self.dir / "artifacts"
        matches = sorted(adir.glob(f"{job_id}__*")) if adir.is_dir() else []
        return matches[0] if matches else None

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
                "conversation_id": d.get("conversation_id"),
                "goal": d.get("goal"),
                "status": d.get("status"),
                "steps": d.get("steps"),
                "created_at": d.get("created_at"),
                "evidence_summary": d.get("evidence_summary"),
                "template": d.get("template", "general"),
                "artifact": d.get("artifact"),
                "cost_usd": (d.get("usage") or {}).get("cost_usd"),
            })
        return out

    # -- durable conversation state ---------------------------------------
    def save_conversation(self, cid: str, state: dict[str, Any]) -> Path | None:
        if not _safe_conv_id(cid):
            return None
        path = self.conversations_dir / f"{cid}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(path)
        return path

    def load_conversation(self, cid: str) -> dict[str, Any] | None:
        if not _safe_conv_id(cid):
            return None
        path = self.conversations_dir / f"{cid}.json"
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    # -- durable event log (reattach / replay) ----------------------------
    def append_event(self, job_id: str, event: dict[str, Any]) -> None:
        if not _safe_id(job_id):
            return
        path = self.events_dir / f"{job_id}.jsonl"
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event) + "\n")
        except OSError:
            pass

    def read_events(self, job_id: str) -> list[dict[str, Any]]:
        if not _safe_id(job_id):
            return []
        path = self.events_dir / f"{job_id}.jsonl"
        out: list[dict[str, Any]] = []
        try:
            for line in path.read_text("utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            return []
        return out

    # -- feedback ---------------------------------------------------------
    def add_feedback(self, job_id: str, rating: str, note: str = "") -> dict[str, Any]:
        row = {"job_id": job_id, "rating": rating, "note": note[:2000],
               "at": time.time()}
        try:
            with (self.dir / "feedback.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        except OSError:
            pass
        return row

    def feedback(self, limit: int = 200) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        try:
            for line in (self.dir / "feedback.jsonl").read_text("utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            return []
        return out[-limit:]

    # -- usage ------------------------------------------------------------
    def usage_summary(self) -> dict[str, Any]:
        total_prompt = total_completion = 0
        total_cost = 0.0
        cost_known = False
        by_day: dict[str, dict[str, Any]] = {}
        runs = 0
        for p in self.dir.glob("job_*.json"):
            try:
                d = json.loads(p.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            usage = d.get("usage") or {}
            runs += 1
            prompt = int(usage.get("prompt_tokens", 0) or 0)
            completion = int(usage.get("completion_tokens", 0) or 0)
            cost = usage.get("cost_usd")
            total_prompt += prompt
            total_completion += completion
            if isinstance(cost, (int, float)):
                total_cost += float(cost)
                cost_known = True
            day = time.strftime("%Y-%m-%d", time.localtime(d.get("created_at") or 0))
            row = by_day.setdefault(day, {"date": day, "runs": 0, "tokens": 0,
                                          "cost_usd": 0.0})
            row["runs"] += 1
            row["tokens"] += prompt + completion
            if isinstance(cost, (int, float)):
                row["cost_usd"] = round(row["cost_usd"] + float(cost), 6)
        budget = _budget()
        return {
            "runs": runs,
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "cost_usd": round(total_cost, 6) if cost_known else None,
            "budget_usd": budget,
            "budget_remaining_usd": (round(max(0.0, budget - total_cost), 6)
                                     if budget is not None else None),
            "by_day": [by_day[k] for k in sorted(by_day)],
        }


def _safe_id(job_id: str) -> bool:
    return (
        isinstance(job_id, str)
        and job_id.startswith("job_")
        and job_id[4:].isalnum()
        and len(job_id) <= 40
    )


def _safe_conv_id(cid: str) -> bool:
    return (
        isinstance(cid, str)
        and cid.startswith("conv_")
        and cid[5:].isalnum()
        and len(cid) <= 40
    )


def _budget() -> float | None:
    import os

    raw = os.environ.get("REVERSEAI_MONTHLY_BUDGET", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
