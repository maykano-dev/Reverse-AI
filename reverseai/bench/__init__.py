"""Benchmark harness — measure the agent against tasks with known outcomes.

This is how ReverseAI's capability is measured over time and how verified
investigation traces are collected for future model training. Each task builds
a target with a known ground truth and a checker that inspects the resulting
Job (not just that it ran).
"""

from .runner import BenchReport, TaskResult, run_suite
from .tasks import BenchTask, builtin_tasks

__all__ = ["BenchTask", "builtin_tasks", "run_suite", "BenchReport", "TaskResult"]
