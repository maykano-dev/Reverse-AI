"""Explicit mission resume worker.

The planner records phases and checkpoints; this module is the missing worker
step. A caller supplies the runner (the CLI uses the normal agent), so resuming a
mission is an explicit action, never an automatic daemon. The checkpoint and
mission record are updated after the run, which makes a second process restart
safe.
"""

from __future__ import annotations

from typing import Any, Callable

from .missions import MissionStore, MissionStoreError


def resume_goal(mission: dict[str, Any]) -> str:
    checkpoints = mission.get("checkpoints") or []
    notes = "\n".join(f"- {c.get('note')}" for c in checkpoints[-12:]) or "- (none)"
    phases = mission.get("phases") or []
    phase_text = "\n".join(
        f"- {p.get('id')}: {p.get('title')} (exit: {p.get('exit')})"
        for p in phases if isinstance(p, dict)) or "- (none)"
    acceptance = "\n".join(f"- {a}" for a in mission.get("acceptance") or []) or "- (none)"
    return (
        f"Resume mission {mission.get('id')} from persisted state. Do not claim "
        "work that is not supported by the checkpoints.\n\n"
        f"Objective: {mission.get('objective')}\n\n"
        f"Acceptance criteria:\n{acceptance}\n\n"
        f"Phases:\n{phase_text}\n\n"
        f"Checkpoints:\n{notes}\n\n"
        "Continue from the next incomplete phase, verify before delivery, and "
        "finish with a concise status."
    )


def resume_mission(store: MissionStore, mission_id: str,
                   runner: Callable[[str], Any]) -> dict[str, Any]:
    """Resume a persisted mission with an injected runner.

    ``runner(goal)`` must return an object with ``id`` and ``status`` (normally a
    Job). A completed run marks the mission done; anything else leaves it paused
    for another explicit resume.
    """
    mission = store.load(mission_id)
    if mission is None:
        raise MissionStoreError("mission not found")
    if mission.get("status") in ("done", "failed", "cancelled"):
        raise MissionStoreError("mission is already terminal")
    mission = store.resume(mission_id)
    goal = resume_goal(mission)
    result = runner(goal)
    job_id = str(getattr(result, "id", "") or "")
    status = str(getattr(result, "status", "") or "failed")
    mission = store.load(mission_id) or mission
    mission["last_job"] = job_id
    mission["last_status"] = status
    mission["last_goal"] = goal[:8000]
    store.save(mission)
    final_status = "done" if status == "completed" else "paused"
    store.checkpoint(mission_id, f"resumed job {job_id}: {status}",
                     status=final_status)
    return store.load(mission_id) or mission
