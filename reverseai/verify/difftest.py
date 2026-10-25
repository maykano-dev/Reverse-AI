"""Differential testing in the sandbox.

Run the original and the modified artifact across a corpus of inputs and compare
observable behavior: exit status, stdout, stderr, and declared output files.
This is how a change is proven *without* trusting the model's description.

Everything runs through ``reverseai.sandbox``. If no isolating backend is
available, the report says ``ran=False`` and the caller must refuse to call the
modification verified.

Corpus safety: args, stdin, files, and output-file names are bounded. Files are
written with ``safe_join`` so a case cannot escape its temporary workdir.
"""

from __future__ import annotations

import base64
import hashlib
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from ..sandbox import SandboxPolicy, create_sandbox
from ..sandbox.result import ExecResult
from ..security.validate import ValidationError, safe_join

MAX_CASES = 32
MAX_ARGS = 32
MAX_ARG_LEN = 512
MAX_STDIN = 64 * 1024
MAX_FILE = 1024 * 1024
MAX_OUTPUT_FILES = 16
MAX_CAPTURE = 8000


class DiffTestError(Exception):
    pass


@dataclass
class InputCase:
    name: str
    args: list[str] = field(default_factory=list)
    stdin: bytes = b""
    files: dict[str, bytes] = field(default_factory=dict)
    expect: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> "InputCase":
        if len(self.args) > MAX_ARGS:
            raise DiffTestError(f"case {self.name!r}: too many args")
        args = []
        for a in self.args:
            a = str(a)
            if len(a) > MAX_ARG_LEN:
                raise DiffTestError(f"case {self.name!r}: argument too long")
            args.append(a)
        stdin = self.stdin or b""
        if isinstance(stdin, str):
            stdin = stdin.encode()
        stdin = bytes(stdin)
        if len(stdin) > MAX_STDIN:
            raise DiffTestError(f"case {self.name!r}: stdin too large")
        files = {}
        for name, data in (self.files or {}).items():
            if len(data) > MAX_FILE:
                raise DiffTestError(f"case {self.name!r}: file {name!r} too large")
            candidate = PurePosixPath(str(name))
            if candidate.is_absolute() or ".." in candidate.parts:
                raise DiffTestError(f"case {self.name!r}: unsafe file name {name!r}")
            files[str(name)] = data
        if not (self.expect or {}) and not isinstance(self.expect, dict):
            raise DiffTestError(f"case {self.name!r}: expect must be an object")
        return InputCase(self.name, args, stdin, files, dict(self.expect or {}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "args": list(self.args),
            "stdin_b64": base64.b64encode(self.stdin).decode("ascii"),
            "files": {name: {"b64": base64.b64encode(data).decode("ascii")}
                      for name, data in self.files.items()},
            "expect": dict(self.expect),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InputCase":
        raw_stdin = d.get("stdin_b64", "")
        if raw_stdin:
            try:
                stdin = base64.b64decode(raw_stdin, validate=True)
            except (ValueError, TypeError) as exc:
                raise DiffTestError(f"case {d.get('name')!r}: invalid stdin_b64") from exc
        else:
            stdin = str(d.get("stdin", "")).encode()
        files: dict[str, bytes] = {}
        raw_files = d.get("files") or {}
        if isinstance(raw_files, list):
            # Backwards-compatible metadata form: names only, no contents.
            raw_files = {str(name): "" for name in raw_files}
        for name, value in raw_files.items():
            if isinstance(value, dict):
                try:
                    files[str(name)] = base64.b64decode(
                        str(value.get("b64", "")), validate=False)
                except (ValueError, TypeError):
                    files[str(name)] = b""
            else:
                files[str(name)] = str(value).encode()
        return cls(str(d.get("name") or "case"), [str(a) for a in d.get("args") or []],
                   stdin, files, dict(d.get("expect") or {}))


@dataclass
class RunSnapshot:
    exit_code: int | None
    term_signal: int | None
    timed_out: bool
    stdout: str
    stderr: str
    output_files: dict[str, dict[str, Any]] = field(default_factory=dict)
    isolation: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def from_exec(cls, r: ExecResult, workdir: str,
                  output_files: list[str]) -> "RunSnapshot":
        files: dict[str, dict[str, Any]] = {}
        for name in output_files[:MAX_OUTPUT_FILES]:
            try:
                p = safe_join(workdir, name)
            except ValidationError:
                continue
            if not p.is_file():
                continue
            try:
                h = hashlib.sha256()
                size = 0
                with p.open("rb") as fh:
                    while True:
                        chunk = fh.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        h.update(chunk)
                        if size > MAX_FILE * 16:
                            break
                with p.open("rb") as fh:
                    head = fh.read(MAX_CAPTURE)
            except OSError:
                continue
            try:
                text = head.decode("utf-8")[:MAX_CAPTURE]
            except UnicodeDecodeError:
                text = None
            files[name] = {
                "size": size,
                "sha256": h.hexdigest(),
                "text": text,
            }
        return cls(
            exit_code=r.exit_code,
            term_signal=r.term_signal,
            timed_out=r.timed_out,
            stdout=r.stdout_text()[:MAX_CAPTURE],
            stderr=r.stderr_text()[:MAX_CAPTURE],
            output_files=files,
            isolation=(r.isolation.to_dict() if r.isolation else {}),
            error=r.error,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CaseResult:
    name: str
    original: RunSnapshot
    modified: RunSnapshot
    differences: list[str] = field(default_factory=list)
    matched: bool = False
    expected: dict[str, Any] = field(default_factory=dict)
    expected_met: bool | None = None
    unexpected: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "matched": self.matched,
            "differences": self.differences,
            "expected": self.expected,
            "expected_met": self.expected_met,
            "unexpected": self.unexpected,
            "notes": self.notes,
            "original": self.original.to_dict(),
            "modified": self.modified.to_dict(),
        }


@dataclass
class DiffReport:
    ran: bool
    cases: list[CaseResult] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    differed: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)
    failed_expectations: list[str] = field(default_factory=list)
    expected_delta_met: bool | None = None
    summary: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ran": self.ran,
            "summary": self.summary,
            "matched": self.matched,
            "differed": self.differed,
            "unexpected": self.unexpected,
            "failed_expectations": self.failed_expectations,
            "expected_delta_met": self.expected_delta_met,
            "error": self.error,
            "cases": [c.to_dict() for c in self.cases],
        }


def _snapshot(target: str, case: InputCase, policy: SandboxPolicy,
              sandbox, output_files: list[str], timeout: float) -> RunSnapshot:
    from dataclasses import replace

    workdir = tempfile.mkdtemp(prefix="rvai-diff-")
    try:
        for name, data in case.files.items():
            dest = safe_join(workdir, name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        p = replace(
            policy,
            allow_untrusted_execution=True,
            workdir=workdir,
            timeout_seconds=timeout,
            ro_binds=list(policy.ro_binds) + [target],
        )
        res = sandbox.run([target] + list(case.args), p, cwd=workdir,
                          stdin=case.stdin)
        return RunSnapshot.from_exec(res, workdir, output_files)
    finally:
        import shutil

        shutil.rmtree(workdir, ignore_errors=True)


def _compare(o: RunSnapshot, m: RunSnapshot,
             output_files: list[str]) -> list[str]:
    diffs: list[str] = []
    if o.exit_code != m.exit_code:
        diffs.append("exit_code")
    if o.term_signal != m.term_signal:
        diffs.append("term_signal")
    if o.timed_out != m.timed_out:
        diffs.append("timed_out")
    if o.stdout != m.stdout:
        diffs.append("stdout")
    if o.stderr != m.stderr:
        diffs.append("stderr")
    for name in output_files:
        a = (o.output_files.get(name) or {}).get("sha256")
        b = (m.output_files.get(name) or {}).get("sha256")
        if a != b:
            diffs.append(f"output_file:{name}")
    return diffs


def _check_expect(case: InputCase, o: RunSnapshot, m: RunSnapshot,
                  matched: bool) -> tuple[bool | None, list[str]]:
    exp = case.expect or {}
    if not exp:
        return None, []
    notes: list[str] = []
    ok = True

    def fail(msg: str) -> None:
        nonlocal ok
        ok = False
        notes.append(msg)

    if "exit_code" in exp and m.exit_code != exp["exit_code"]:
        fail(f"modified exit {m.exit_code} != expected {exp['exit_code']}")
    if "stdout" in exp and m.stdout.strip() != str(exp["stdout"]).strip():
        fail("modified stdout did not match the expected text")
    if "stderr" in exp and m.stderr.strip() != str(exp["stderr"]).strip():
        fail("modified stderr did not match the expected text")
    for needle in _as_list(exp.get("stdout_contains")):
        if needle not in m.stdout:
            fail(f"modified stdout does not contain {needle!r}")
    for needle in _as_list(exp.get("stderr_contains")):
        if needle not in m.stderr:
            fail(f"modified stderr does not contain {needle!r}")
    if "differs" in exp and bool(exp["differs"]) == matched:
        fail("expected the behavior to differ" if exp["differs"]
             else "expected the behavior to match the original")
    if "same_as_original" in exp and bool(exp["same_as_original"]) != matched:
        fail("expected the behavior to match the original" if exp["same_as_original"]
             else "expected the behavior to differ from the original")
    expected_files = exp.get("output_files") or {}
    if isinstance(expected_files, dict):
        for name, want in expected_files.items():
            got = (m.output_files.get(name) or {})
            if isinstance(want, str):
                if (got.get("text") or "").strip() != want.strip():
                    fail(f"output file {name!r} did not match")
            elif got.get("sha256") != want:
                fail(f"output file {name!r} hash did not match")
    return ok, notes


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _case_unexpected(case: InputCase, matched: bool) -> bool:
    exp = case.expect or {}
    if exp.get("same_as_original") is True and not matched:
        return True
    if exp.get("differs") is False and not matched:
        return True
    return False


def generate_corpus(seed_args: list[list[str]] | None = None) -> list[InputCase]:
    """A small, safe default corpus. Targeted cases can replace or extend it."""
    cases = [
        InputCase("empty", [], b""),
        InputCase("help", ["--help"], b""),
        InputCase("version", ["--version"], b""),
        InputCase("stdin-empty", [], b""),
        InputCase("stdin-text", [], b"hello differential test\n"),
        InputCase("numbers", ["0", "1", "-1", "255"], b""),
        InputCase("boundary-long", ["A" * 128], b""),
        InputCase("file-input", [], b"", {"input.txt": b"seed\n"}),
    ]
    for i, args in enumerate(seed_args or []):
        cases.append(InputCase(f"seed-{i + 1}", [str(a) for a in args], b""))
    return [c.normalized() for c in cases[:MAX_CASES]]


def run_differential(
    original_path: str,
    modified_path: str,
    cases: list[InputCase] | None = None,
    policy: SandboxPolicy | None = None,
    output_files: list[str] | None = None,
    timeout_seconds: float = 10.0,
) -> DiffReport:
    """Run both artifacts over the corpus and compare observable behavior."""
    output_files = [str(n) for n in (output_files or [])][:MAX_OUTPUT_FILES]
    try:
        normalized = [c.normalized() for c in (cases or generate_corpus())]
    except DiffTestError as exc:
        return DiffReport(ran=False, error=str(exc))
    if not normalized:
        return DiffReport(ran=False, error="empty differential corpus")
    if len(normalized) > MAX_CASES:
        return DiffReport(ran=False, error=f"too many cases (max {MAX_CASES})")

    base = policy or SandboxPolicy()
    timeout = min(max(float(timeout_seconds or base.timeout_seconds), 0.1), 60.0)
    from dataclasses import replace

    try:
        sandbox = create_sandbox(replace(base, allow_untrusted_execution=True))
    except Exception as exc:  # no isolating backend on this host
        return DiffReport(ran=False, error=f"sandbox unavailable: {exc}")

    results: list[CaseResult] = []
    for case in normalized:
        o = _snapshot(original_path, case, base, sandbox, output_files, timeout)
        m = _snapshot(modified_path, case, base, sandbox, output_files, timeout)
        diffs = _compare(o, m, output_files)
        matched = not diffs
        exp_met, notes = _check_expect(case, o, m, matched)
        result = CaseResult(
            name=case.name, original=o, modified=m, differences=diffs,
            matched=matched, expected=case.expect, expected_met=exp_met,
            unexpected=_case_unexpected(case, matched), notes=notes,
        )
        results.append(result)

    matched_names = [r.name for r in results if r.matched]
    differed_names = [r.name for r in results if not r.matched]
    unexpected = [r.name for r in results if r.unexpected]
    failed = [r.name for r in results if r.expected_met is False]
    with_expect = [r for r in results if r.expected_met is not None]
    expected_met = all(r.expected_met for r in with_expect) if with_expect else None
    summary = (
        f"{len(results)} input(s): {len(matched_names)} matched, "
        f"{len(differed_names)} differed"
    )
    if with_expect:
        summary += ("; expected delta met" if expected_met else
                    "; expected delta NOT met")
    if unexpected:
        summary += f"; {len(unexpected)} unexpected regression(s)"
    return DiffReport(
        ran=True, cases=results, matched=matched_names, differed=differed_names,
        unexpected=unexpected, failed_expectations=failed,
        expected_delta_met=expected_met, summary=summary,
    )
