"""Bounded verify-and-repair loop.

A modification is not verified because it built, launched, or "looks right". It
is verified only when a behavioral test passes in the sandbox. If the test fails,
the loop can hand the failure back to a repair function (typically the model),
which proposes another candidate, up to a hard attempt limit.

The loop is deliberately independent of the agent: ``repair_fn`` is injected, so
tests can use a deterministic repair and production can use the model provider.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from .difftest import DiffReport, InputCase, run_differential

DEFAULT_MAX_ATTEMPTS = 3
MAX_MAX_ATTEMPTS = 10


def default_max_attempts() -> int:
    raw = os.environ.get("REVERSEAI_MAX_REPAIR_ATTEMPTS", "").strip()
    try:
        n = int(raw) if raw else DEFAULT_MAX_ATTEMPTS
    except ValueError:
        n = DEFAULT_MAX_ATTEMPTS
    return max(1, min(n, MAX_MAX_ATTEMPTS))


@dataclass
class Attempt:
    attempt: int
    passed: bool
    reason: str
    path: str = ""
    report: dict[str, Any] = field(default_factory=dict)
    repaired: bool = False
    repair_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepairResult:
    verified: bool
    attempts: list[Attempt]
    final_path: str
    reason: str
    passed_tests: int = 0
    test_summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "passed_tests": self.passed_tests,
            "attempts": [a.to_dict() for a in self.attempts],
            "final_path": self.final_path,
            "reason": self.reason,
            "test_summary": self.test_summary,
        }


def verification_passes(report: DiffReport) -> tuple[bool, str, int]:
    """Decide whether a differential report is real proof of the intended change.

    A pass requires: the sandbox ran, every declared expectation was met, there
    was no unexpected regression, and the modified program actually differed on
    at least one input. A no-op patch is not a verified change, even if the
    caller only declared regression checks.
    """
    if not report.ran:
        return False, f"could not run a behavioral test: {report.error}", 0
    if report.unexpected:
        return (False,
                "unexpected regression on: " + ", ".join(report.unexpected), 0)
    if report.expected_delta_met is not True:
        return (False,
                "the declared expected behavior was not demonstrated", 0)
    passed = sum(1 for c in report.cases if c.expected_met is True)
    if passed <= 0:
        return False, "no behavioral expectation was declared", 0
    if not any(not c.matched for c in report.cases):
        return (False,
                "the modified program behaved identically; no change was demonstrated",
                0)
    return True, report.summary, passed


RepairFn = Callable[[Attempt, int], str | None]
EventFn = Callable[[dict[str, Any]], None]


class RepairLoop:
    def __init__(
        self,
        original_path: str,
        modified_path: str,
        cases: list[InputCase],
        *,
        policy=None,
        output_files: list[str] | None = None,
        timeout_seconds: float = 10.0,
        max_attempts: int | None = None,
        repair_fn: RepairFn | None = None,
        on_event: EventFn | None = None,
    ) -> None:
        self.original_path = original_path
        self.modified_path = modified_path
        self.cases = cases
        self.policy = policy
        self.output_files = output_files or []
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(
            1, min(int(max_attempts or default_max_attempts()), MAX_MAX_ATTEMPTS))
        self.repair_fn = repair_fn
        self.on_event = on_event

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:
                pass

    def run(self) -> RepairResult:
        current = self.modified_path
        attempts: list[Attempt] = []
        last_report: DiffReport | None = None
        last_reason = "no behavioral test ran"

        self._emit({
            "type": "verification_plan",
            "title": "Checking the change before delivery",
            "detail": (f"Running {len(self.cases)} behavioral input(s) in the "
                       f"sandbox, up to {self.max_attempts} attempt(s)."),
            "max_attempts": self.max_attempts,
            "cases": [c.name for c in self.cases],
        })

        for n in range(1, self.max_attempts + 1):
            report = run_differential(
                self.original_path, current, self.cases, self.policy,
                output_files=self.output_files,
                timeout_seconds=self.timeout_seconds,
            )
            last_report = report
            passed, reason, passed_count = verification_passes(report)
            last_reason = reason
            attempt = Attempt(
                attempt=n, passed=passed, reason=reason, path=str(current),
                report=report.to_dict(), repaired=n > 1,
            )
            attempts.append(attempt)
            self._emit({
                "type": "verification_attempt",
                "attempt": n,
                "max_attempts": self.max_attempts,
                "passed": passed,
                "reason": reason,
                "summary": report.summary,
                "report_ran": report.ran,
            })
            if passed:
                self._emit({
                    "type": "verification",
                    "verified": True,
                    "attempts": n,
                    "reason": reason,
                    "passed_tests": passed_count,
                })
                return RepairResult(
                    verified=True, attempts=attempts, final_path=str(current),
                    reason=reason, passed_tests=passed_count,
                    test_summary=report.to_dict(),
                )

            if n >= self.max_attempts:
                break
            if self.repair_fn is None:
                last_reason = reason + "; no repair was attempted"
                break
            self._emit({
                "type": "verification_repair",
                "attempt": n,
                "detail": "The test failed; asking for another candidate.",
            })
            try:
                candidate = self.repair_fn(attempt, n)
            except Exception as exc:
                candidate = None
                attempt.repair_error = f"{type(exc).__name__}: {exc}"
            if not candidate:
                last_reason = reason + "; the repair produced no candidate"
                break
            if not os.path.isfile(candidate):
                last_reason = reason + "; the repair candidate does not exist"
                break
            current = candidate

        reason = (f"Not verified after {len(attempts)} attempt(s): {last_reason}")
        self._emit({
            "type": "verification",
            "verified": False,
            "attempts": len(attempts),
            "reason": reason,
            "passed_tests": 0,
        })
        return RepairResult(
            verified=False, attempts=attempts, final_path=str(current),
            reason=reason, passed_tests=0,
            test_summary=last_report.to_dict() if last_report else {},
        )
