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
            if status != "running":
                mission.pop("lease_owner", None)
                mission.pop("lease_until", None)
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

    def claim(self, mission_id: str, owner: str,
              lease_s: float = 300.0, now: float | None = None) -> dict[str, Any]:
        """Claim a mission for one explicit worker, with a time-bounded lease."""
        mission = self.load(mission_id)
        if mission is None:
            raise MissionStoreError("mission not found")
        if mission.get("status") in ("done", "failed", "cancelled"):
            raise MissionStoreError("mission is already terminal")
        now = time.time() if now is None else float(now)
        until = float(mission.get("lease_until") or 0)
        holder = str(mission.get("lease_owner") or "")
        if mission.get("status") == "running" and until > now and holder != owner:
            raise MissionStoreError(
                f"mission is leased by {holder or 'another worker'} until {until:.0f}")
        mission["status"] = "running"
        mission["lease_owner"] = owner
        mission["lease_until"] = now + max(1.0, float(lease_s))
        mission["claimed_at"] = now
        self.save(mission)
        return mission

    def release(self, mission_id: str, owner: str | None = None,
                status: str | None = None) -> dict[str, Any]:
        mission = self.load(mission_id)
        if mission is None:
            raise MissionStoreError("mission not found")
        if owner and mission.get("lease_owner") not in (None, owner):
            raise MissionStoreError("mission lease is held by another worker")
        mission.pop("lease_owner", None)
        mission.pop("lease_until", None)
        if status:
            mission["status"] = status
        self.save(mission)
        return mission

    def due(self, now: float | None = None) -> list[dict[str, Any]]:
        """Missions a worker may claim: planned, paused, or expired leases."""
        now = time.time() if now is None else float(now)
        out = []
        for mission in self.list():
            status = mission.get("status")
            if status in ("planned", "paused"):
                out.append(mission)
            elif status == "running" and float(mission.get("lease_until") or 0) <= now:
                out.append(mission)
        out.sort(key=lambda m: float(m.get("updated_at") or m.get("created_at") or 0))
        return out
