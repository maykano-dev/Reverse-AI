"""Durable mission state for long-running work.

The planner produces a mission; this store makes it survive a process restart. It
records checkpoints and status, but it does not execute phases. A worker must
claim a mission explicitly.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


class MissionStoreError(Exception):
    pass


class MissionStore:
    def __init__(self, directory: str | os.PathLike) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, mission_id: str) -> Path:
        if not (mission_id.startswith("mission_") and
                all(c.isalnum() or c in "_-" for c in mission_id)):
            raise MissionStoreError("invalid mission id")
        return self.dir / f"{mission_id}.json"

    def save(self, mission: dict[str, Any]) -> Path:
        mid = str(mission.get("id") or "")
        if not mid:
            raise MissionStoreError("mission needs an id")
        path = self._path(mid)
        payload = {**mission, "updated_at": time.time()}
        fd, tmp = tempfile.mkstemp(prefix=".mission-", dir=str(self.dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return path

    def load(self, mission_id: str) -> dict[str, Any] | None:
        try:
            return json.loads(self._path(mission_id).read_text("utf-8"))
        except (OSError, json.JSONDecodeError, MissionStoreError):
            return None

    def list(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self.dir.glob("mission_*.json"), reverse=True):
            try:
                out.append(json.loads(p.read_text("utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return out

    def checkpoint(self, mission_id: str, note: str,
                   status: str | None = None) -> dict[str, Any]:
        mission = self.load(mission_id)
        if mission is None:
            raise MissionStoreError("mission not found")
        mission.setdefault("checkpoints", []).append({
            "at": time.time(), "note": str(note)[:1000],
        })
        if status:
            mission["status"] = status
        self.save(mission)
        return mission

    def resume(self, mission_id: str) -> dict[str, Any]:
        mission = self.load(mission_id)
        if mission is None:
            raise MissionStoreError("mission not found")
        if mission.get("status") in ("done", "failed", "cancelled"):
            raise MissionStoreError("mission is already terminal")
        mission["status"] = "running"
        mission.setdefault("resume_count", 0)
        mission["resume_count"] += 1
        self.save(mission)
        return mission
