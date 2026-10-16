"""Benchmark runner — execute tasks against an agent and score the outcomes."""

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "pass_rate": round(self.pass_rate, 3),
            "results": [r.to_dict() for r in self.results],
        }

    def render(self) -> str:
        lines = [f"Benchmark: {self.passed}/{self.total} passed "
                 f"({self.pass_rate * 100:.0f}%)", ""]
        for r in self.results:
            mark = "PASS" if r.passed else "FAIL"
            lines.append(f"  [{mark}] {r.task_id}: {r.notes} "
                         f"(steps={r.steps}, {r.duration_s:.1f}s)")
        return "\n".join(lines)


def run_task(task: BenchTask, factory: AgentFactory) -> TaskResult:
    if not task.available():
        return TaskResult(task.id, False, "skipped: toolchain unavailable",
                          "skipped", 0, 0.0)
    with tempfile.TemporaryDirectory(prefix=f"bench-{task.id}-") as wd:
        try:
            target = task.setup(Path(wd))
        except Exception as exc:  # setup failure
            return TaskResult(task.id, False, f"setup error: {exc}", "error", 0, 0.0,
                              error=str(exc))
        agent = factory(task.permission)
        start = time.monotonic()
        try:
            job = agent.run(task.goal, target_path=target)
        except Exception as exc:
            return TaskResult(task.id, False, f"run error: {exc}", "error", 0,
                              time.monotonic() - start, error=str(exc))
        dur = time.monotonic() - start
        try:
            passed, notes = task.check(job)
        except Exception as exc:
            passed, notes = False, f"checker error: {exc}"
        tools = sorted({e.tool for e in agent.mediator.audit if e.allowed})
        return TaskResult(
            task_id=task.id, passed=passed, notes=notes, status=job.status,
            steps=job.steps, duration_s=dur,
            evidence=job.evidence.summary(), tools_used=tools,
        )


def run_suite(factory: AgentFactory, tasks: list[BenchTask] | None = None) -> BenchReport:
    tasks = tasks if tasks is not None else builtin_tasks()
    results = [run_task(t, factory) for t in tasks]
    passed = sum(1 for r in results if r.passed)
    return BenchReport(total=len(results), passed=passed, results=results)
