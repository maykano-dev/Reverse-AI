"""Agent tools for verification, differential testing, and repair.

``verify_modification`` is the only tool that can mark a modification verified.
It runs a declared behavioral test in the sandbox, optionally asks the model for
another candidate when the test fails, and records a bounded attempt history.

``differential_test`` is the exploratory harness. It reports matches, differences,
and unexpected regressions, but it does not authorize delivery by itself.

Both tools are EXECUTE tier: they run candidate code only through the sandbox.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..modify import BytePatch, PatchError, apply_byte_patches
from ..naming import artifact_name
from ..sandbox import SandboxPolicy
from ..verify import (
    DiffTestError,
    InputCase,
    RepairLoop,
    generate_corpus,
    run_differential,
)
from ..verify.fuzz import FuzzError, fuzz_differential
from ..verify.mutation import (
    MutationError, assess_mutations, generate_string_mutations,
)
from ..verify.repair import default_max_attempts
from .corpus_tools import corpus_cases_for
from .tools import Permission, Tool, ToolContext, ToolResult


def _emit(ctx: ToolContext, event: dict[str, Any]) -> None:
    fn = ctx.extra.get("emit")
    if callable(fn):
        try:
            fn(event)
        except Exception:
            pass


def _b64(value: str) -> bytes:
    import base64

    return base64.b64decode(value, validate=True)


def _files_from(value: Any) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    if not isinstance(value, dict):
        return out
    for name, content in value.items():
        if isinstance(content, str):
            out[str(name)] = content.encode()
        elif isinstance(content, dict) and "b64" in content:
            out[str(name)] = _b64(str(content["b64"]))
        else:
            out[str(name)] = str(content).encode()
    return out


# Natural aliases a model tends to use for the exit code inside an expect dict.
_EXIT_ALIASES = ("exit", "status", "returncode", "return_code", "code")


def _apply_flat(exp: dict[str, Any], src: dict[str, Any]) -> None:
    """Apply flat expect_* / flag keys from a source (args or a case) into exp."""
    if "expect_stdout" in src:
        exp["stdout"] = src["expect_stdout"]
    if "expect_stderr" in src:
        exp["stderr"] = src["expect_stderr"]
    if "expect_exit" in src:
        exp["exit_code"] = src["expect_exit"]
    if "expect_diff" in src:
        exp["differs"] = bool(src["expect_diff"])
    if "differs" in src:
        exp["differs"] = bool(src["differs"])
    if "same_as_original" in src:
        exp["same_as_original"] = bool(src["same_as_original"])
    if "stdout_contains" in src:
        exp["stdout_contains"] = src["stdout_contains"]
    if "stderr_contains" in src:
        exp["stderr_contains"] = src["stderr_contains"]
    if "output_files" in src and isinstance(src["output_files"], dict):
        exp["output_files"] = src["output_files"]


def _normalize_exit(exp: dict[str, Any]) -> None:
    """Map 'exit'/'status'/'code'/... inside an expect dict to 'exit_code'."""
    for alias in _EXIT_ALIASES:
        if alias in exp:
            exp.setdefault("exit_code", exp.pop(alias))
        else:
            exp.pop(alias, None)


def _expectation(args: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    exp = dict(args.get("expect") or {})
    if isinstance(case.get("expect"), dict):
        exp.update(case["expect"])
    # The model naturally writes {"exit": 0, "stdout": "..."} inside a case's
    # expect; the matcher keys on exit_code, so normalize the alias.
    _normalize_exit(exp)
    # Flat expect_* / flags may appear at the args level (global) or on the case
    # itself; the case takes precedence.
    _apply_flat(exp, args)
    _apply_flat(exp, case)
    return exp


def build_cases(args: dict[str, Any]) -> list[InputCase]:
    cases_in = args.get("cases")
    if isinstance(cases_in, list) and cases_in:
        if len(cases_in) > 32:
            raise DiffTestError("too many cases (max 32)")
        cases: list[InputCase] = []
        for i, raw in enumerate(cases_in):
            if not isinstance(raw, dict):
                raise DiffTestError("each case must be an object")
            c = InputCase.from_dict(raw)
            c.name = c.name or f"case-{i + 1}"
            c.expect = _expectation(args, raw)
            cases.append(c.normalized())
        return cases

    stdin = args.get("stdin", "")
    if args.get("stdin_b64"):
        stdin = _b64(str(args["stdin_b64"]))
    elif isinstance(stdin, str):
        stdin = stdin.encode()
    case = InputCase(
        name="behavioral",
        args=[str(a) for a in args.get("args") or []],
        stdin=stdin if isinstance(stdin, bytes) else b"",
        files=_files_from(args.get("files")),
        expect=_expectation(args, {}),
    )
    return [case.normalized()]


_CASE_KEYS = {
    "args", "stdin", "stdin_b64", "files", "expect_stdout", "expect_stderr",
    "expect_exit", "expect_diff", "same_as_original", "stdout_contains",
    "stderr_contains", "output_files",
}


def has_case_input(args: dict[str, Any]) -> bool:
    return bool(args.get("cases")) or any(k in args for k in _CASE_KEYS)


def _has_expectation(cases: list[InputCase]) -> bool:
    return any(bool(c.expect) for c in cases)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _parse_repair_json(text: str | None) -> list[dict[str, Any]]:
    if not text:
        return []
    raw = text.strip()
    if "```" in raw:
        raw = raw.split("```", 2)[1] if raw.count("```") >= 2 else raw
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return []
    try:
        payload = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return []
    patches = payload.get("patches")
    return patches if isinstance(patches, list) else []


def _model_repair(ctx: ToolContext, original: str, attempt, n: int) -> str | None:
    """Ask the provider for a concrete patch set after a failed test."""
    provider = ctx.extra.get("provider")
    if provider is None:
        return None
    from .providers.base import Message, Role

    last_patches = ctx.extra.get("last_patches") or []
    failure = {
        "attempt": n,
        "reason": attempt.reason,
        "summary": (attempt.report or {}).get("summary", ""),
        "differences": [
            {"input": c.get("name"), "differences": c.get("differences"),
             "modified": (c.get("modified") or {}).get("stdout", "")[:1200]}
            for c in (attempt.report or {}).get("cases", [])[:6]
        ],
        "prior_patches": last_patches[:12],
    }
    prompt = (
        "A binary modification failed its behavioral test. Propose a repair as "
        "a complete patch set applied to the ORIGINAL file. Return JSON only, "
        "with this shape:\n"
        '{"patches":[{"offset":123,"hex":"4e4557","expect_hex":"4f4c44"}]}\n'
        "Use file offsets and exact hex. Do not include prose. If you cannot "
        "propose a safe patch, return {\"patches\":[]}.\n\n"
        f"Failure evidence:\n{json.dumps(failure, indent=2)}"
    )
    try:
        resp = provider.chat(
            [Message(Role.SYSTEM,
                     "You repair byte-level binary modifications. Output JSON only."),
             Message(Role.USER, prompt)],
            tools=None, temperature=0.0, max_tokens=1200)
    except Exception:
        return None
    raw_patches = _parse_repair_json(resp.content)
    if not raw_patches or len(raw_patches) > 100:
        return None
    patches = []
    try:
        for p in raw_patches:
            if not isinstance(p, dict):
                return None
            patches.append(BytePatch(
                offset=int(p["offset"]),
                data=bytes.fromhex(str(p["hex"])),
                expected_original=(bytes.fromhex(str(p["expect_hex"]))
                                   if p.get("expect_hex") else None),
            ))
    except (KeyError, ValueError, TypeError):
        return None
    suffix = Path(original).suffix
    out_name = artifact_name(original, ctx.goal, "repair", suffix=suffix)
    try:
        result = apply_byte_patches(original, patches, ctx.workspace,
                                    out_name=out_name)
    except (PatchError, OSError):
        return None
    ctx.extra["modified_path"] = result.output_path
    ctx.extra["modified_operation"] = "patch"
    ctx.extra["modified_turn"] = ctx.job_id
    ctx.extra["modified_label"] = "Repaired copy"
    ctx.extra["last_patches"] = result.details
    _emit(ctx, {
        "type": "verification_repair",
        "attempt": n,
        "detail": f"Applied {result.patches_applied} repair patch(es) to a fresh copy.",
    })
    return result.output_path


class VerifyModificationTool(Tool):
    name = "verify_modification"
    description = (
        "Prove a modification with a behavioral test in the sandbox. Run the "
        "original and modified artifacts on the same declared inputs, compare "
        "exit status, stdout, stderr, and output files, and optionally repair a "
        "failure and try again. A modification is NEVER delivered as verified "
        "unless this test passes. Declare at least one expectation, for example "
        "expect_stdout, expect_exit, or a cases list with expectations."
    )
    parameters = {
        "type": "object",
        "properties": {
            "args": {"type": "array", "items": {"type": "string"}},
            "stdin": {"type": "string"},
            "files": {"type": "object",
                      "description": "input file name -> text content"},
            "expect_stdout": {"type": "string"},
            "expect_stderr": {"type": "string"},
            "expect_exit": {"type": "integer"},
            "expect_diff": {"type": "boolean",
                            "description": "the modified behavior must differ"},
            "same_as_original": {"type": "boolean",
                                 "description": "the behavior must match"},
            "stdout_contains": {"type": "array", "items": {"type": "string"}},
            "stderr_contains": {"type": "array", "items": {"type": "string"}},
            "output_files": {"type": "object",
                             "description": "declared output name -> expected text"},
            "cases": {"type": "array", "items": {"type": "object"},
                      "description": "targeted cases: name, args, stdin, files, expect"},
            "use_corpus": {"type": "boolean", "default": False,
                           "description": "include captured regression cases for this target"},
            "corpus_exclude": {"type": "array", "items": {"type": "string"},
                               "description": "captured case names to leave out"},
            "max_attempts": {"type": "integer", "minimum": 1, "maximum": 10},
            "timeout_seconds": {"type": "number", "minimum": 0.1, "default": 10},
            "repair": {"type": "boolean", "default": True,
                       "description": "ask the model for a repair after a failure"},
        },
    }
    permission = Permission.EXECUTE

    def run(self, args, ctx) -> ToolResult:
        if not ctx.target_path:
            return ToolResult.failure("no target set for this job")
        modified = args.get("modified") or ctx.extra.get("modified_path")
        if not modified:
            return ToolResult.failure(
                "no modified artifact yet - apply a patch first")
        if not Path(modified).is_file():
            return ToolResult.failure(f"modified artifact is missing: {modified}")

        try:
            cases = build_cases(args) if has_case_input(args) else []
            corpus = corpus_cases_for(ctx, args)
        except DiffTestError as exc:
            return ToolResult.failure(f"bad verification case: {exc}")
        if args.get("use_corpus") and not corpus:
            reason = ("No captured behavioral corpus exists for this target. "
                      "Capture one first with capture_behavior_corpus.")
            ctx.extra["verification"] = {
                "verified": False, "passed_tests": 0, "attempts": [],
                "reason": reason, "tests_run": 0, "test_summary": {},
                "artifact_path": str(modified), "turn": ctx.job_id,
            }
            ctx.extra["delivery"] = {"allowed": False, "reason": reason}
            return ToolResult.failure(reason)
        cases += corpus

        if not _has_expectation(cases):
            reason = (
                "No behavioral expectation was declared. A comparison alone is "
                "not proof, so delivery is blocked. Declare expect_stdout, "
                "expect_exit, expect_diff, or a cases list with expectations.")
            verification = {
                "verified": False,
                "passed_tests": 0,
                "attempts": [],
                "reason": reason,
                "artifact_path": str(modified),
                "tests_run": 0,
                "test_summary": {},
                "modified_sha256": _sha256(modified),
            }
            verification["turn"] = ctx.job_id
            ctx.extra["verification"] = verification
            ctx.extra["delivery"] = {"allowed": False, "reason": reason}
            if ctx.evidence is not None:
                ctx.evidence.observed(reason, source=self.name)
            _emit(ctx, {"type": "verification", "verified": False,
                        "attempts": 0, "reason": reason, "passed_tests": 0})
            return ToolResult.failure(reason, content=reason)

        from dataclasses import replace

        base = ctx.sandbox_policy or SandboxPolicy()
        timeout = min(max(float(args.get("timeout_seconds", 10)), 0.1), 60.0)
        policy = replace(base, allow_untrusted_execution=True,
                         timeout_seconds=timeout)
        output_files = list(args.get("output_files") or [])
        if isinstance(args.get("output_files"), dict):
            output_files = list(args["output_files"].keys())

        repair_fn = None
        if args.get("repair", True) and ctx.extra.get("provider") is not None:
            repair_fn = lambda attempt, n: _model_repair(ctx, ctx.target_path, attempt, n)

        loop = RepairLoop(
            ctx.target_path, modified, cases, policy=policy,
            output_files=[str(x) for x in output_files][:16],
            timeout_seconds=timeout,
            max_attempts=args.get("max_attempts") or default_max_attempts(),
            repair_fn=repair_fn,
            on_event=lambda ev: _emit(ctx, ev),
        )
        result = loop.run()

        verification = result.to_dict()
        verification.update({
            "kind": "behavioral",
            "turn": ctx.job_id,
            "artifact_path": result.final_path,
            "tests_run": len(result.attempts),
            "modified_sha256": _sha256(result.final_path),
            "differential": (result.test_summary or {}).get("summary", ""),
            "corpus_controls": len(corpus),
        })
        ctx.extra["verification"] = verification
        if result.verified:
            ctx.extra["modified_path"] = result.final_path
            ctx.extra["delivery"] = {
                "allowed": True,
                "reason": f"behavioral test passed in the sandbox "
                          f"({result.passed_tests} expectation(s))",
            }
            if ctx.evidence is not None:
                ctx.evidence.verified(
                    f"behavioral test passed: {result.reason}",
                    source=self.name,
                    detail=(result.test_summary or {}).get("summary", ""))
            content = (
                f"Verified after {len(result.attempts)} attempt(s).\n"
                f"{result.reason}\n"
                f"Final artifact: {result.final_path}"
            )
            return ToolResult.success(content, **verification)

        reason = result.reason
        ctx.extra["delivery"] = {"allowed": False, "reason": reason}
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"behavioral verification failed: {reason}", source=self.name)
        content = (
            f"NOT verified. The artifact will not be delivered.\n{reason}\n"
            f"Attempts: {len(result.attempts)}"
        )
        return ToolResult(ok=False, content=content, data=verification,
                          error=reason)


class AssessTestStrengthTool(Tool):
    name = "assess_test_strength"
    description = (
        "Mutate the modified artifact in small, deterministic ways and run the "
        "same behavioral corpus against every mutant. A corpus that cannot "
        "detect a broken mutant is weak. Returns a mutation score, the cases "
        "that killed each mutation, and the weak cases. This measures test "
        "strength; it does not authorize delivery."
    )
    parameters = {
        "type": "object",
        "properties": {
            "cases": {"type": "array", "items": {"type": "object"}},
            "use_corpus": {"type": "boolean", "default": False},
            "mutations": {"type": "array", "items": {"type": "object"},
                          "description": "optional explicit offset/hex mutations"},
            "max_mutations": {"type": "integer", "minimum": 1, "maximum": 12,
                              "default": 6},
            "timeout_seconds": {"type": "number", "minimum": 0.1, "default": 10},
        },
    }
    permission = Permission.EXECUTE

    def run(self, args, ctx) -> ToolResult:
        if not ctx.target_path:
            return ToolResult.failure("no target set for this job")
        modified = ctx.extra.get("modified_path")
        if not modified:
            return ToolResult.failure(
                "no modified artifact yet - apply a patch first")
        try:
            cases = build_cases(args) if args.get("cases") else []
            cases += corpus_cases_for(ctx, args)
        except DiffTestError as exc:
            return ToolResult.failure(f"bad test corpus: {exc}")
        if not cases:
            return ToolResult.failure(
                "provide at least one behavioral case or enable use_corpus")
        mutations = []
        for raw in args.get("mutations") or []:
            if not isinstance(raw, dict):
                continue
            try:
                from ..verify.mutation import Mutation
                mutations.append(Mutation(
                    str(raw.get("name") or f"mutation-{len(mutations) + 1}"),
                    int(raw["offset"]), str(raw["original"]),
                    str(raw["replacement"]),
                    str(raw.get("description") or "")))
            except (KeyError, ValueError, TypeError) as exc:
                return ToolResult.failure(f"bad mutation: {exc}")
        if not mutations:
            try:
                from ..core import analyze_file
                report = analyze_file(ctx.target_path)
                mutations = generate_string_mutations(
                    ctx.target_path, modified,
                    list(report.strings_sample or []),
                    max_mutations=int(args.get("max_mutations", 6)))
            except Exception as exc:
                return ToolResult.failure(
                    f"could not generate mutations: {exc}")
        if not mutations:
            return ToolResult.failure(
                "no safe mutations could be generated; provide explicit ones")
        base = ctx.sandbox_policy or SandboxPolicy()
        timeout = min(max(float(args.get("timeout_seconds", 10)), 0.1), 60.0)
        try:
            result = assess_mutations(
                ctx.target_path, modified, cases, mutations, policy=base,
                timeout_seconds=timeout)
        except MutationError as exc:
            return ToolResult.failure(str(exc))
        data = result.to_dict()
        ctx.extra["test_strength"] = data
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"mutation score {result.mutation_score:.0%} "
                f"({result.killed}/{result.total} detected)",
                source=self.name, detail=result.note)
        content = (
            f"mutation score: {result.mutation_score:.0%} "
            f"({result.killed}/{result.total})\n"
            f"weak cases: {', '.join(result.weak_cases) or 'none'}\n"
            f"{result.note}")
        return ToolResult.success(content, **data)


class DifferentialFuzzTool(Tool):
    name = "differential_fuzz"
    description = (
        "Mutate declared seed inputs and compare the original and modified "
        "artifacts on every generated case in the sandbox. Reports behavior "
        "differences, crash signals, and timeouts. Bounded sampling, not proof."
    )
    parameters = {
        "type": "object",
        "properties": {
            "cases": {"type": "array", "items": {"type": "object"}},
            "iterations": {"type": "integer", "minimum": 1, "maximum": 32,
                           "default": 16},
            "seed": {"type": "integer", "default": 0},
            "timeout_seconds": {"type": "number", "minimum": 0.1, "default": 10},
        },
    }
    permission = Permission.EXECUTE

    def run(self, args, ctx) -> ToolResult:
        if not ctx.target_path:
            return ToolResult.failure("no target set for this job")
        modified = ctx.extra.get("modified_path")
        if not modified:
            return ToolResult.failure("no modified artifact yet - apply a patch first")
        try:
            seeds = build_cases(args) if args.get("cases") else generate_corpus()
        except DiffTestError as exc:
            return ToolResult.failure(f"bad fuzz seeds: {exc}")
        base = ctx.sandbox_policy or SandboxPolicy()
        timeout = min(max(float(args.get("timeout_seconds", 10)), 0.1), 60.0)
        try:
            result = fuzz_differential(
                ctx.target_path, modified, seeds,
                iterations=int(args.get("iterations", 16)),
                policy=base, timeout_seconds=timeout,
                seed=int(args.get("seed", 0)))
        except FuzzError as exc:
            return ToolResult.failure(str(exc))
        if not result.ran:
            return ToolResult.failure(f"fuzzing could not run: {result.error}")
        ctx.extra["fuzz"] = result.to_dict()
        if ctx.evidence is not None:
            ctx.evidence.observed(result.summary, source=self.name)
        return ToolResult(ok=not result.differences,
                          content=result.summary,
                          data=result.to_dict(),
                          error=("unexpected fuzz difference" if result.differences
                                 else None))


class DifferentialTestTool(Tool):
    name = "differential_test"
    description = (
        "Run the original and modified artifacts across a corpus of inputs in "
        "the sandbox and compare exit status, stdout, stderr, and declared output "
        "files. Reports matches, differences, and unexpected regressions. Use it "
        "to explore behavior; use verify_modification to authorize delivery."
    )
    parameters = {
        "type": "object",
        "properties": {
            "cases": {"type": "array", "items": {"type": "object"}},
            "output_files": {"type": "array", "items": {"type": "string"}},
            "timeout_seconds": {"type": "number", "minimum": 0.1, "default": 10},
        },
    }
    permission = Permission.EXECUTE

    def run(self, args, ctx) -> ToolResult:
        if not ctx.target_path:
            return ToolResult.failure("no target set for this job")
        modified = ctx.extra.get("modified_path")
        if not modified:
            return ToolResult.failure(
                "no modified artifact yet - apply a patch first")
        try:
            cases = build_cases(args) if args.get("cases") else generate_corpus()
        except DiffTestError as exc:
            return ToolResult.failure(f"bad differential corpus: {exc}")
        base = ctx.sandbox_policy or SandboxPolicy()
        timeout = min(max(float(args.get("timeout_seconds", 10)), 0.1), 60.0)
        report = run_differential(
            ctx.target_path, modified, cases, policy=base,
            output_files=[str(x) for x in args.get("output_files") or []],
            timeout_seconds=timeout)
        data = report.to_dict()
        ctx.extra["differential"] = data
        ctx.extra["differential_turn"] = ctx.job_id
        if not report.ran:
            return ToolResult.failure(
                f"differential test could not run: {report.error}",
                content=f"Sandbox unavailable: {report.error}")
        if ctx.evidence is not None:
            if report.unexpected:
                ctx.evidence.observed(
                    "differential test found unexpected regression(s): "
                    + ", ".join(report.unexpected), source=self.name)
            else:
                ctx.evidence.observed(
                    "differential test: " + report.summary, source=self.name)
        return ToolResult.success(
            report.summary + ("\nUnexpected: " + ", ".join(report.unexpected)
                              if report.unexpected else ""),
            **data)
