"""Benchmark tasks with ground-truth checkers.

A task builds a target (when needed), supplies the natural-language goal and the
permission ceiling the agent should run under, and checks the finished Job.
Checkers inspect evidence/outcome, not merely whether the loop completed.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..agent.job import Job
from ..agent.tools import Permission

# setup(workdir) -> target_path or None ; check(job) -> (passed, notes)
SetupFn = Callable[[Path], str | None]
CheckFn = Callable[[Job], "tuple[bool, str]"]


@dataclass
class BenchTask:
    id: str
    description: str
    goal: str
    setup: SetupFn
    check: CheckFn
    permission: Permission = Permission.EXECUTE
    needs_cc: bool = False
    tags: list[str] = field(default_factory=list)

    def available(self) -> bool:
        return not self.needs_cc or shutil.which("cc") is not None


def _compile(workdir: Path, name: str, marker: str) -> str:
    src = workdir / f"{name}.c"
    src.write_text(f'#include <stdio.h>\nint main(){{puts("{marker}");return 0;}}\n')
    out = workdir / name
    subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(out)],
                   check=True, capture_output=True)
    return str(out)


# --- checkers ---

def _observed_contains(job: Job, needle: str) -> bool:
    return any(needle in f.claim.lower()
               for f in job.evidence.all())


def _check_identify(job: Job) -> tuple[bool, str]:
    if job.status != "completed":
        return False, f"status={job.status}"
    ok = _observed_contains(job, "elf")
    return ok, "found elf in evidence" if ok else "no elf observation recorded"


def _check_runs_marker(marker: str) -> CheckFn:
    def _c(job: Job) -> tuple[bool, str]:
        if job.status != "completed":
            return False, f"status={job.status}"
        ok = marker in job.final_answer or _observed_contains(job, marker.lower())
        return ok, f"marker {'present' if ok else 'absent'} in conclusion"
    return _c


def _check_verified(job: Job) -> tuple[bool, str]:
    if job.status != "completed":
        return False, f"status={job.status}"
    verified = job.evidence.summary().get("verified", 0)
    return verified >= 1, f"{verified} verified finding(s)"


def builtin_tasks() -> list[BenchTask]:
    return [
        BenchTask(
            id="identify_format",
            description="Identify the format and architecture of an ELF binary.",
            goal="Identify this file's format and CPU architecture. Analyze it, "
                 "then state what it is.",
            setup=lambda w: _compile(w, "ident", "IDENT_OK"),
            check=_check_identify,
            permission=Permission.READ,
            needs_cc=True,
            tags=["analysis"],
        ),
        BenchTask(
            id="run_and_report",
            description="Run a program in the sandbox and report its output.",
            goal="Run this program safely and tell me exactly what text it prints.",
            setup=lambda w: _compile(w, "runner", "BENCH_MARKER_42"),
            check=_check_runs_marker("BENCH_MARKER_42"),
            permission=Permission.EXECUTE,
            needs_cc=True,
            tags=["execution"],
        ),
        BenchTask(
            id="patch_and_verify",
            description="Patch a printed string and verify the change by running.",
            goal="This program prints OLD. Change it to print NEW instead, on a "
                 "copy, then verify by running both and comparing output.",
            setup=lambda w: _compile(w, "patcher", "OLD"),
            check=_check_verified,
            permission=Permission.WRITE,
            needs_cc=True,
            tags=["modify", "verify"],
        ),
    ]
