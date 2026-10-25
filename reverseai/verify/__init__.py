"""Verification — prove (or disprove) that a modification did what was intended
without breaking what worked, by comparing behavior in the sandbox.

A modification is verified only by a passing behavioral test. ``repair`` adds a
bounded retry loop, ``difftest`` runs an input corpus, and ``report`` produces a
signed, self-contained record.
"""

from .difftest import (
    CaseResult,
    DiffReport,
    DiffTestError,
    InputCase,
    RunSnapshot,
    generate_corpus,
    run_differential,
)
from .regression import VerificationReport, compare_execution
from .repair import Attempt, RepairLoop, RepairResult, verification_passes
from .corpus import CorpusError, CorpusStore, capture_corpus, target_sha256
from .replay import load_cases, replay_record, write_reports
from .report import (
    ReportError,
    build_from_job,
    build_report,
    render_html,
    render_json,
    sign_report,
    verify_signature,
)

__all__ = [
    "VerificationReport",
    "compare_execution",
    "InputCase",
    "RunSnapshot",
    "CaseResult",
    "DiffReport",
    "DiffTestError",
    "generate_corpus",
    "run_differential",
    "Attempt",
    "RepairLoop",
    "RepairResult",
    "verification_passes",
    "ReportError",
    "build_report",
    "build_from_job",
    "render_json",
    "render_html",
    "sign_report",
    "verify_signature",
    "CorpusStore",
    "CorpusError",
    "capture_corpus",
    "target_sha256",
    "load_cases",
    "replay_record",
    "write_reports",
]
