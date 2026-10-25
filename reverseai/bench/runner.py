"""Benchmark runner — execute tasks and score outcomes, not just completions."""

from __future__ import annotations

import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..agent.orchestrator import Agent
from ..agent.tools import Permission
from .tasks import BenchTask, builtin_tasks

# factory(permission) -> Agent configured at that permission ceiling
AgentFactory = Callable[[Permission], Agent]


@dataclass
class TaskResult:
    task_id: str
    passed: bool
    notes: str
    status: str
    steps: int
    duration_s: float
    evidence: dict[str, int] = field(default_factory=dict)
    tools_used: list[str] = field(default_factory=list)
    error: str | None = None
    split: str = "dev"
    category: str = "general"
    verified: bool = False
    regression: bool = False
    repair_attempts: int = 0
    refused: bool = False
    expected_refusal: bool = False
    false_verification: bool = False
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchReport:
    total: int
    passed: int
    results: list[TaskResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    @property
    def verified_success(self) -> int:
        return sum(1 for r in self.results if r.passed and r.verified)

    @property
    def regression_rate(self) -> float:
        return (sum(1 for r in self.results if r.regression) / self.total
                if self.total else 0.0)

    @property
    def repair_tasks(self) -> list[TaskResult]:
        return [r for r in self.results if r.repair_attempts > 0]

    @property
    def repair_success_rate(self) -> float | None:
        tasks = self.repair_tasks
        if not tasks:
            return None
        return sum(1 for r in tasks if r.passed) / len(tasks)

    @property
    def false_verification_rate(self) -> float:
        return (sum(1 for r in self.results if r.false_verification) / self.total
                if self.total else 0.0)

    @property
    def refusal_rate(self) -> float | None:
        expected = [r for r in self.results if r.expected_refusal]
        if not expected:
            return None
        return sum(1 for r in expected if r.refused) / len(expected)

    @property
    def cost_per_verified(self) -> float | None:
        if not self.verified_success:
            return None
        return round(sum(r.cost_usd for r in self.results) / self.verified_success, 6)

    @property
    def time_per_verified(self) -> float | None:
        if not self.verified_success:
            return None
        return round(sum(r.duration_s for r in self.results) / self.verified_success, 3)

    def by_split(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for split in sorted({r.split for r in self.results}):
            rows = [r for r in self.results if r.split == split]
            out[split] = {
                "total": len(rows),
                "passed": sum(1 for r in rows if r.passed),
                "verified": sum(1 for r in rows if r.passed and r.verified),
                "pass_rate": round(sum(1 for r in rows if r.passed) / len(rows), 3),
            }
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "pass_rate": round(self.pass_rate, 3),
            "verified_success": self.verified_success,
            "regression_rate": round(self.regression_rate, 3),
            "repair_success_rate": (round(self.repair_success_rate, 3)
                                    if self.repair_success_rate is not None else None),
            "false_verification_rate": round(self.false_verification_rate, 3),
            "refusal_rate": (round(self.refusal_rate, 3)
                             if self.refusal_rate is not None else None),
            "cost_per_verified": self.cost_per_verified,
            "time_per_verified": self.time_per_verified,
            "by_split": self.by_split(),
            "results": [r.to_dict() for r in self.results],
        }

    def render(self) -> str:
        lines = [f"Benchmark: {self.passed}/{self.total} passed "
                 f"({self.pass_rate * 100:.0f}%)", ""]
        lines.append(f"verified success: {self.verified_success}")
        lines.append(f"regression rate: {self.regression_rate * 100:.0f}%")
        if self.repair_success_rate is not None:
            lines.append(f"repair success: {self.repair_success_rate * 100:.0f}%")
        lines.append(f"false verification rate: "
                     f"{self.false_verification_rate * 100:.0f}%")
        if self.refusal_rate is not None:
            lines.append(f"appropriate refusal rate: {self.refusal_rate * 100:.0f}%")
        if self.cost_per_verified is not None:
            lines.append(f"cost per verified task: ${self.cost_per_verified:.4f}")
        if self.time_per_verified is not None:
            lines.append(f"time per verified task: {self.time_per_verified:.1f}s")
        for split, row in self.by_split().items():
            lines.append(f"  {split}: {row['passed']}/{row['total']} "
                         f"({row['pass_rate'] * 100:.0f}%)")
        lines.append("")
        for r in self.results:
            mark = "PASS" if r.passed else "FAIL"
            tags = []
            if r.verified:
                tags.append("verified")
            if r.regression:
                tags.append("regression")
            if r.false_verification:
                tags.append("FALSE-VERIFY")
            if r.expected_refusal:
                tags.append("refusal-expected")
            lines.append(f"  [{mark}] {r.task_id}: {r.notes} "
                         f"(steps={r.steps}, {r.duration_s:.1f}s"
                         f"{', ' + ', '.join(tags) if tags else ''})")
        return "\n".join(lines)


def run_task(task: BenchTask, factory: AgentFactory) -> TaskResult:
    if not task.available():
        return TaskResult(task.id, False, "skipped: toolchain unavailable",
                          "skipped", 0, 0.0, split=task.split,
                          category=task.category,
                          expected_refusal=task.expects_refusal)
    with tempfile.TemporaryDirectory(prefix=f"bench-{task.id}-") as wd:
        try:
            target = task.setup(Path(wd))
        except Exception as exc:  # setup failure
            return TaskResult(task.id, False, f"setup error: {exc}", "error", 0,
                              0.0, error=str(exc), split=task.split,
                              category=task.category,
                              expected_refusal=task.expects_refusal)
        agent = factory(task.permission)
        start = time.monotonic()
        try:
            job = agent.run(task.goal, target_path=target)
        except Exception as exc:
            return TaskResult(task.id, False, f"run error: {exc}", "error", 0,
                              time.monotonic() - start, error=str(exc),
                              split=task.split, category=task.category,
                              expected_refusal=task.expects_refusal)
        dur = time.monotonic() - start
        try:
            passed, notes = task.check(job)
        except Exception as exc:
            passed, notes = False, f"checker error: {exc}"
        tools = sorted({e.tool for e in agent.mediator.audit if e.allowed})
        verification = job.verification or {}
        verified = bool(verification.get("verified")) and bool(
            job.delivery.get("allowed"))
        unexpected = (verification.get("test_summary") or {}).get("unexpected") or []
        attempts = verification.get("attempts") or []
        refused = bool(job.artifact is None
                       and not (job.delivery or {}).get("allowed"))
        # A verified artifact for a task that requires refusal is a serious
        # benchmark failure: the system proved the wrong outcome confidently.
        false_verification = bool(
            (task.expects_refusal and job.delivery.get("allowed"))
            or (not passed and verified and not task.expects_refusal))
        usage = job.usage or {}
        cost = usage.get("cost_usd")
        return TaskResult(
            task_id=task.id, passed=passed, notes=notes, status=job.status,
            steps=job.steps, duration_s=dur,
            evidence=job.evidence.summary(), tools_used=tools,
            split=task.split, category=task.category, verified=verified,
            regression=bool(unexpected),
            repair_attempts=max(0, len(attempts) - 1),
            refused=refused, expected_refusal=task.expects_refusal,
            false_verification=false_verification,
            cost_usd=float(cost or 0.0),
        )


def run_suite(factory: AgentFactory, tasks: list[BenchTask] | None = None,
              *, split: str | None = None) -> BenchReport:
    tasks = tasks if tasks is not None else builtin_tasks()
    if split:
        tasks = [t for t in tasks if t.split == split]
    results = [run_task(t, factory) for t in tasks]
    passed = sum(1 for r in results if r.passed)
    return BenchReport(total=len(results), passed=passed, results=results)
