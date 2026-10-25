"""Routines — scheduled agent tasks ("every morning, brief me on ...").

A small, durable scheduler for the single-process server. Schedules are stored
as plain JSON and evaluated in local time. Supported forms::

    {"kind": "once",     "at": "2026-10-25T09:00"}
    {"kind": "daily",    "time": "08:00"}
    {"kind": "weekdays", "time": "09:00"}
    {"kind": "weekly",   "weekday": 0, "time": "09:00"}   # Monday=0
    {"kind": "every",    "minutes": 120}

Routines run only while the server is running; a missed run is not replayed
(except ``once``, which stays due until it runs). That is honest behavior for a
local-first app and avoids surprise token spend after downtime.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _parse_time(value: str) -> tuple[int, int]:
    try:
        hh, mm = (value or "09:00").split(":", 1)
        hh, mm = int(hh), int(mm)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except (ValueError, AttributeError):
        pass
    return 9, 0


def _at(now: datetime, hh: int, mm: int) -> datetime:
    return now.replace(hour=hh, minute=mm, second=0, microsecond=0)


def compute_next(schedule: dict[str, Any], now: datetime | None = None,
                 last_run: float | None = None) -> float | None:
    """Return the next run time as a Unix timestamp, or None if finished."""
    now = now or datetime.now()
    kind = (schedule or {}).get("kind", "daily")
    if kind == "once":
        raw = schedule.get("at")
        try:
            at = datetime.fromisoformat(str(raw))
        except (ValueError, TypeError):
            return None
        return at.timestamp() if at.timestamp() > now.timestamp() else None

    if kind == "every":
        try:
            minutes = max(1, int(schedule.get("minutes", 60)))
        except (ValueError, TypeError):
            minutes = 60
        base = datetime.fromtimestamp(last_run) if last_run else now
        nxt = base + timedelta(minutes=minutes)
        while nxt <= now:
            nxt += timedelta(minutes=minutes)
        return nxt.timestamp()

    hh, mm = _parse_time(str(schedule.get("time", "09:00")))
    if kind == "daily":
        nxt = _at(now, hh, mm)
        if nxt <= now:
            nxt += timedelta(days=1)
        return nxt.timestamp()

    if kind == "weekdays":
        nxt = _at(now, hh, mm)
        for _ in range(8):
            if nxt > now and nxt.weekday() < 5:
                return nxt.timestamp()
            nxt += timedelta(days=1)
        return None

    if kind == "weekly":
        try:
            weekday = int(schedule.get("weekday", 0))
        except (ValueError, TypeError):
            weekday = 0
        weekday = max(0, min(6, weekday))
        nxt = _at(now, hh, mm)
        days = (weekday - nxt.weekday()) % 7
        nxt += timedelta(days=days)
        if nxt <= now:
            nxt += timedelta(days=7)
        return nxt.timestamp()

    return None


@dataclass
class Routine:
    id: str
    name: str
    goal: str
    schedule: dict[str, Any]
    template: str = "general"
    target: str | None = None
    permission: str = "write"
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    last_run: float | None = None
    next_run: float | None = None
    last_job: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Routine":
        return cls(
            id=str(d.get("id") or f"rt_{uuid.uuid4().hex[:8]}"),
            name=str(d.get("name") or "Routine"),
            goal=str(d.get("goal") or ""),
            schedule=dict(d.get("schedule") or {"kind": "daily", "time": "09:00"}),
            template=str(d.get("template") or "general"),
            target=d.get("target") or None,
            permission=str(d.get("permission") or "write"),
            enabled=bool(d.get("enabled", True)),
            created_at=float(d.get("created_at") or time.time()),
            last_run=d.get("last_run"),
            next_run=d.get("next_run"),
            last_job=d.get("last_job"),
        )


class RoutineStore:
    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._routines: list[Routine] = self._load()

    def _load(self) -> list[Routine]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = data.get("routines") if isinstance(data, dict) else data
        return [Routine.from_dict(r) for r in rows or [] if isinstance(r, dict)]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "routines": [r.to_dict() for r in self._routines]},
                             indent=2)
        fd, tmp = tempfile.mkstemp(prefix=".routines-", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def all(self) -> list[Routine]:
        with self._lock:
            return [Routine.from_dict(r.to_dict()) for r in self._routines]

    def get(self, routine_id: str) -> Routine | None:
        with self._lock:
            for r in self._routines:
                if r.id == routine_id:
                    return Routine.from_dict(r.to_dict())
        return None

    def add(self, name: str, goal: str, schedule: dict[str, Any],
            template: str = "general", target: str | None = None,
            permission: str = "write", now: datetime | None = None) -> Routine:
        if not (goal or "").strip():
            raise ValueError("routine goal is empty")
        r = Routine(
            id=f"rt_{uuid.uuid4().hex[:8]}",
            name=(name or goal).strip()[:80],
            goal=goal.strip(),
            schedule=schedule,
            template=template,
            target=target,
            permission=permission,
        )
        r.next_run = compute_next(r.schedule, now)
        with self._lock:
            self._routines.append(r)
            self._save()
        return Routine.from_dict(r.to_dict())

    def update(self, routine: Routine, now: datetime | None = None) -> Routine:
        with self._lock:
            for i, r in enumerate(self._routines):
                if r.id == routine.id:
                    if routine.enabled and routine.next_run is None:
                        routine.next_run = compute_next(routine.schedule, now, routine.last_run)
                    self._routines[i] = routine
                    self._save()
                    return Routine.from_dict(routine.to_dict())
        raise KeyError(routine.id)

    def delete(self, routine_id: str) -> bool:
        with self._lock:
            before = len(self._routines)
            self._routines = [r for r in self._routines if r.id != routine_id]
            changed = len(self._routines) != before
            if changed:
                self._save()
        return changed

    def due(self, now: datetime | None = None) -> list[Routine]:
        now = now or datetime.now()
        ts = now.timestamp()
        with self._lock:
            return [Routine.from_dict(r.to_dict()) for r in self._routines
                    if r.enabled and r.next_run is not None and r.next_run <= ts]


class RoutineScheduler:
    """Background loop that starts due routines through the RunManager."""

    def __init__(self, store: RoutineStore, runs, interval: float = 20.0) -> None:
        self.store = store
        self.runs = runs
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="reverseai-routines")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.run_due()
            except Exception:
                pass

    def run_due(self, now: datetime | None = None) -> list[str]:
        now = now or datetime.now()
        started: list[str] = []
        for r in self.store.due(now):
            live = self.runs.get(r.last_job) if r.last_job else None
            if live is not None and not live.done.is_set():
                continue  # previous run still working
            stream_id, _cid, error = self.runs.start({
                "goal": r.goal,
                "target": r.target,
                "template": r.template,
                "permission": r.permission,
            })
            if error or not stream_id:
                continue
            r.last_run = now.timestamp()
            r.last_job = stream_id
            if r.schedule.get("kind") == "once":
                r.enabled = False
                r.next_run = None
            else:
                r.next_run = compute_next(r.schedule, now, r.last_run)
            self.store.update(r, now)
            started.append(stream_id)
        return started
