"""Bounded differential fuzzing.

Generate small mutations of declared seed inputs, run the original and the
modified artifact in the sandbox, and report behavior differences, crashes, and
timeouts. This is a sampling tool, not proof of correctness.
"""

from __future__ import annotations

import base64
import random
from dataclasses import dataclass, field
from typing import Any

from ..sandbox import SandboxPolicy
from .difftest import DiffReport, InputCase, run_differential

MAX_ITERATIONS = 32
MAX_STDIN = 16 * 1024


class FuzzError(Exception):
    pass


@dataclass
class FuzzReport:
    ran: bool
    iterations: int
    cases: int
    differences: list[str] = field(default_factory=list)
    crashes: list[str] = field(default_factory=list)
    timeouts: list[str] = field(default_factory=list)
    summary: str = ""
    error: str | None = None
    report: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran, "iterations": self.iterations,
            "cases": self.cases, "differences": self.differences,
            "crashes": self.crashes, "timeouts": self.timeouts,
            "summary": self.summary, "error": self.error,
            "report": self.report,
        }


def _mutate(data: bytes, rng: random.Random) -> bytes:
    if not data:
        return bytes([rng.randrange(0, 256)])
    buf = bytearray(data[:MAX_STDIN])
    op = rng.choice(("flip", "insert", "delete", "splice"))
    if op == "flip":
        i = rng.randrange(len(buf))
        buf[i] ^= 1 << rng.randrange(0, 8)
    elif op == "insert":
        i = rng.randrange(len(buf) + 1)
        buf[i:i] = bytes([rng.randrange(0, 256)])
    elif op == "delete" and len(buf) > 1:
        i = rng.randrange(len(buf))
        del buf[i]
    else:
        i = rng.randrange(len(buf))
        j = rng.randrange(len(buf))
        buf[i:i] = buf[j:j + min(8, len(buf) - j)]
    return bytes(buf[:MAX_STDIN])


def fuzz_differential(
    original_path: str,
    modified_path: str,
    seeds: list[InputCase],
    *,
    iterations: int = 16,
    policy: SandboxPolicy | None = None,
    timeout_seconds: float = 10.0,
    seed: int = 0,
) -> FuzzReport:
    if not seeds:
        raise FuzzError("fuzzing needs at least one seed case")
    iterations = max(1, min(int(iterations), MAX_ITERATIONS))
    rng = random.Random(seed)
    cases: list[InputCase] = []
    for i in range(iterations):
        base = seeds[i % len(seeds)]
        mutated = _mutate(base.stdin, rng)
        cases.append(InputCase(
            f"fuzz-{i + 1}", list(base.args), mutated,
            dict(base.files), {}))
    report: DiffReport = run_differential(
        original_path, modified_path, cases, policy=policy,
        timeout_seconds=timeout_seconds)
    if not report.ran:
        return FuzzReport(False, iterations, len(cases), error=report.error)
    diffs = []
    crashes = []
    timeouts = []
    for c in report.cases:
        if not c.matched:
            diffs.append(c.name)
        for side in (c.original, c.modified):
            if side.timed_out:
                timeouts.append(c.name)
            elif side.term_signal is not None:
                crashes.append(c.name)
    summary = (f"{len(report.cases)} fuzz case(s): {len(diffs)} differed, "
               f"{len(crashes)} crash signal(s), {len(timeouts)} timeout(s)")
    return FuzzReport(True, iterations, len(report.cases), sorted(set(diffs)),
                      sorted(set(crashes)), sorted(set(timeouts)), summary,
                      report=report.to_dict())
