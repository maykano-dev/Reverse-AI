"""Behavioral regression comparison.

Runs the original and the modified binary in the sandbox with identical inputs
and reports how their observable behavior differs. This is what turns "it built"
into evidence a change actually worked — the core honesty primitive from the
security/evidence model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from dataclasses import replace
from typing import Any

from ..sandbox import SandboxPolicy, create_sandbox
from ..sandbox.result import ExecResult


@dataclass
class RunSummary:
    exit_code: int | None
    term_signal: int | None
    timed_out: bool
    stdout: str
    stderr: str
    duration_s: float

    @classmethod
    def from_exec(cls, r: ExecResult, cap: int = 4000) -> "RunSummary":
        return cls(
            exit_code=r.exit_code,
            term_signal=r.term_signal,
            timed_out=r.timed_out,
            stdout=r.stdout_text()[:cap],
            stderr=r.stderr_text()[:cap],
            duration_s=round(r.duration_s, 4),
        )


@dataclass
class VerificationReport:
    ran: bool
    original: RunSummary | None = None
    modified: RunSummary | None = None
    same_exit: bool = False
    same_stdout: bool = False
    same_stderr: bool = False
    verdict: str = ""
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "original": asdict(self.original) if self.original else None,
            "modified": asdict(self.modified) if self.modified else None,
            "same_exit": self.same_exit,
            "same_stdout": self.same_stdout,
            "same_stderr": self.same_stderr,
            "verdict": self.verdict,
            "notes": self.notes,
            "error": self.error,
        }


def compare_execution(
    original_path: str,
    modified_path: str,
    args: list[str] | None = None,
    policy: SandboxPolicy | None = None,
    stdin: bytes | None = None,
) -> VerificationReport:
    """Execute both binaries in the sandbox with the same args and diff behavior."""
    args = args or []
    base = policy or SandboxPolicy()

    def _run(path: str) -> ExecResult:
        p = replace(base, allow_untrusted_execution=True,
                    ro_binds=list(base.ro_binds) + [path])
        sb = create_sandbox(p)
        return sb.run([path] + [str(a) for a in args], p, stdin=stdin)

    try:
        orig = _run(original_path)
        mod = _run(modified_path)
    except Exception as exc:  # host/config problem
        return VerificationReport(ran=False, error=f"{type(exc).__name__}: {exc}")

    o = RunSummary.from_exec(orig)
    m = RunSummary.from_exec(mod)
    same_exit = o.exit_code == m.exit_code and o.term_signal == m.term_signal
    same_out = o.stdout == m.stdout
    same_err = o.stderr == m.stderr

    notes: list[str] = []
    if orig.error:
        notes.append(f"original run error: {orig.error}")
    if mod.error:
        notes.append(f"modified run error: {mod.error}")
    if o.timed_out or m.timed_out:
        notes.append("one or both runs timed out")

    if same_exit and same_out and same_err:
        verdict = "identical — modification produced no observable behavioral change"
    elif same_exit and not (same_out and same_err):
        verdict = "same exit status, different output — behavior changed as expected or regressed"
    else:
        verdict = "exit status differs — behavior materially changed; inspect intent vs regression"

    return VerificationReport(
        ran=True, original=o, modified=m,
        same_exit=same_exit, same_stdout=same_out, same_stderr=same_err,
        verdict=verdict, notes=notes,
    )
