"""Reproducible verification outside the agent loop.

The agent's signed report is useful, but teams need to re-run the same proof
without a model or an API key. This module turns a differential run into the
same verification record shape the report builder already understands, and
builds a replay recipe that can be executed with ``python3 -m reverseai verify``.

Everything runs through the sandbox. If the host cannot isolate the target, the
result is an honest failure, never a host-side execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import time
from pathlib import Path
from typing import Any

from ..sandbox import SandboxPolicy
from .difftest import DiffReport, InputCase, run_differential
from .report import build_report, render_html, render_json


class ReplayError(Exception):
    pass


def sha256_file(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError as exc:
        raise ReplayError(f"could not hash {path}: {exc}") from exc
    return h.hexdigest()


def load_cases(path: str | os.PathLike) -> list[InputCase]:
    """Load a case list from JSON: either a list or ``{"cases": [...]}``."""
    try:
        data = json.loads(Path(path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError(f"could not read cases: {exc}") from exc
    rows = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        raise ReplayError("case file must contain a non-empty list")
    out: list[InputCase] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ReplayError(f"case {i} is not an object")
        try:
            out.append(InputCase.from_dict(row).normalized())
        except Exception as exc:
            raise ReplayError(f"case {i}: {exc}") from exc
    return out


def dump_cases(cases: list[InputCase], path: str | os.PathLike) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "cases": [c.to_dict() for c in cases]}
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def _passed(report: DiffReport) -> list[str]:
    return [c.name for c in report.cases
            if c.expected_met is True and not c.unexpected]


def _failed(report: DiffReport) -> list[str]:
    return [c.name for c in report.cases
            if c.expected_met is False or c.unexpected]


def verification_from_diff(report: DiffReport,
                           original_path: str,
                           modified_path: str) -> dict[str, Any]:
    passed = _passed(report)
    failed = _failed(report)
    verified = bool(report.ran and passed and not failed)
    if not report.ran:
        reason = f"verification could not run: {report.error}"
    elif verified:
        reason = report.summary or "behavioral test passed"
    else:
        parts = []
        if report.unexpected:
            parts.append("unexpected regression on: " + ", ".join(report.unexpected))
        if report.failed_expectations:
            parts.append("failed expectation on: "
                         + ", ".join(report.failed_expectations))
        if not passed:
            parts.append("no declared expectation passed")
        reason = "; ".join(parts) or "the behavioral test did not pass"

    attempt = {
        "attempt": 1,
        "passed": verified,
        "reason": reason,
        "report": report.to_dict(),
    }
    return {
        "verified": verified,
        "kind": "behavioral",
        "turn": "cli",
        "reason": reason,
        "passed_tests": len(passed),
        "tests_run": len(report.cases),
        "attempts": [attempt],
        "test_summary": {
            "summary": report.summary,
            "matched": report.matched,
            "differed": report.differed,
            "unexpected": report.unexpected,
            "expected_delta_met": report.expected_delta_met,
        },
        "differential": report.summary,
        "artifact_path": str(Path(modified_path).resolve()),
        "modified_sha256": sha256_file(modified_path),
        "original_sha256": sha256_file(original_path),
        "corpus_controls": sum(1 for c in report.cases
                               if (c.expected or {}).get("same_as_original") is True),
    }


def replay_record(
    original_path: str,
    modified_path: str,
    cases: list[InputCase],
    *,
    goal: str = "",
    policy: SandboxPolicy | None = None,
    output_files: list[str] | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    report = run_differential(
        original_path, modified_path, cases, policy=policy,
        output_files=output_files, timeout_seconds=timeout_seconds)
    verification = verification_from_diff(report, original_path, modified_path)
    delivery = {
        "allowed": bool(verification["verified"]),
        "reason": ("behavioral test passed in the sandbox"
                   if verification["verified"] else verification["reason"]),
    }
    record = {
        "id": "cli_" + verification["modified_sha256"][:12],
        "goal": goal or "Verify a modification against a behavioral corpus",
        "target_path": str(Path(original_path).resolve()),
        "status": "completed",
        "artifact": Path(modified_path).name,
        "artifact_meta": {
            "name": Path(modified_path).name,
            "path": str(Path(modified_path).resolve()),
            "size": Path(modified_path).stat().st_size,
            "sha256": verification["modified_sha256"],
        },
        "verification": verification,
        "delivery": delivery,
        "mode": "direct",
        "modification_plan": {
            "strategy": "byte_patch",
            "steps": [
                {"id": "investigate", "title": "Inspect the target",
                 "status": "done"},
                {"id": "verify", "title": "Run the behavioral corpus",
                 "status": "done" if verification["verified"] else "failed"},
            ],
            "blast_radius": {"level": "unknown"},
        },
        "evidence": [
            {"claim": f"compared {len(report.cases)} input(s)",
             "confidence": "observed", "source": "reverseai verify",
             "detail": report.summary},
        ],
        "finished_at": time.time(),
        "replay_cases": [c.to_dict() for c in cases],
    }
    return record


def replay_recipe(record: dict[str, Any]) -> dict[str, Any]:
    """A machine-readable description of how to re-run the verification."""
    verification = record.get("verification") or {}
    cases = record.get("replay_cases") or []
    artifact_meta = record.get("artifact_meta") or {}
    target = record.get("target_path") or ""
    modified = artifact_meta.get("path") or ""
    names = []
    for c in cases:
        if isinstance(c, dict):
            names.append({"name": c.get("name"), "args": c.get("args") or []})
    if not names:
        for attempt in verification.get("attempts") or []:
            for c in (attempt.get("report") or {}).get("cases") or []:
                names.append({"name": c.get("name"), "args": c.get("args") or []})
    command = ""
    if target:
        parts = ["python3", "-m", "reverseai", "verify",
                 "--original", target]
        if modified:
            parts += ["--modified", modified]
        parts += ["--cases", "cases.json", "--report", "report.json"]
        command = " ".join(shlex.quote(p) for p in parts)
    return {
        "original": target,
        "modified": modified or artifact_meta.get("name", ""),
        "original_sha256": verification.get("original_sha256", ""),
        "modified_sha256": artifact_meta.get("sha256", ""),
        "case_count": (len(cases) or int(verification.get("tests_run", 0) or 0)),
        "cases": names,
        "command": command,
    }


def write_reports(record: dict[str, Any], path: str | os.PathLike) -> dict[str, Any]:
    """Write a signed JSON or HTML report. Returns the report object."""
    report = build_report(record)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix.lower() in (".html", ".htm"):
        p.write_text(render_html(report), encoding="utf-8")
    else:
        p.write_text(render_json(report), encoding="utf-8")
    return report
