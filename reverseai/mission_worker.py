"""Lease-based mission worker.

The worker is explicit: it can run once from the CLI or loop as a foreground
daemon. It claims missions, runs the injected runner, records the outcome, and
releases the lease. A second process cannot claim a live lease.
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable

from .mission_runner import resume_goal
from .missions import MissionStore, MissionStoreError


def _record(store: MissionStore, mission_id: str, result: Any) -> dict[str, Any]:
    job_id = str(getattr(result, "id", "") or "")
    status = str(getattr(result, "status", "") or "failed")
    mission = store.load(mission_id) or {}
    mission["last_job"] = job_id
    mission["last_status"] = status
    store.save(mission)
    final = "done" if status == "completed" else "paused"
    store.checkpoint(mission_id, f"worker job {job_id}: {status}", status=final)
    return store.load(mission_id) or mission


def run_once(store: MissionStore, runner: Callable[[str], Any], *,
             owner: str, limit: int = 1, lease_s: float = 300.0,
             now: float | None = None) -> list[dict[str, Any]]:
    """Claim and run up to ``limit`` due missions once."""
    results: list[dict[str, Any]] = []
    for mission in store.due(now)[:max(1, int(limit))]:
        mid = str(mission.get("id") or "")
        if not mid:
            continue
        try:
            claimed = store.claim(mid, owner, lease_s=lease_s, now=now)
        except MissionStoreError as exc:
            results.append({"id": mid, "ok": False, "error": str(exc)})
            continue
        goal = resume_goal(claimed)
        try:
            outcome = runner(goal)
        except Exception as exc:  # a worker crash must not leave a live lease
            try:
                store.checkpoint(mid, f"worker error: {exc}", status="paused")
                store.release(mid, owner)
            except Exception:
                pass
            results.append({"id": mid, "ok": False, "error": str(exc)})
            continue
        try:
            updated = _record(store, mid, outcome)
        except Exception as exc:
            results.append({"id": mid, "ok": False, "error": str(exc)})
            continue
        results.append({"id": mid, "ok": True, "status": updated.get("status"),
                        "job": updated.get("last_job")})
    return results


def run_worker(store_dir: str, runner: Callable[[str], Any], *,
               owner: str | None = None, once: bool = False,
               interval: float = 10.0, limit: int = 1,
               lease_s: float = 300.0,
               should_stop: Callable[[], bool] | None = None) -> int:
    """Run one pass or a foreground loop. Returns the number of missions handled."""
    store = MissionStore(store_dir)
    owner = owner or f"{os.uname().nodename}-{os.getpid()}"
    total = 0
    while True:
        results = run_once(store, runner, owner=owner, limit=limit,
                           lease_s=lease_s)
        total += len([r for r in results if r.get("ok")])
        if once:
            return total
        if should_stop and should_stop():
            return total
        time.sleep(max(1.0, float(interval)))
