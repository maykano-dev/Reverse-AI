"""Autonomous modification tools.

Two tools:

  choose_modification_strategy (READ)
      Inspect the target with the pure analysis core and explain which strategy
      fits the request, with alternatives and confidence.

  plan_and_modify (WRITE)
      Choose, plan, scope, implement through the existing executors, and prove
      the result with verify_modification. It cannot deliver an artifact itself:
      the conversation delivery gate still requires a passing behavioral test.

The engine never executes target code directly. Implementation goes through the
existing modification tools, and verification goes through the sandbox-backed
verify/repair loop.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..core import analyze_file
from ..modify.planner import (
    ModificationPlan,
    build_plan,
    mark_step,
    preserve_rest,
)
from ..modify.strategy import STRATEGY_LABELS, choose_strategy
from ..security.validate import ValidationError, read_target
from ..verify import DiffTestError, InputCase
from .tools import Permission, Tool, ToolContext, ToolResult
from .verify_tools import build_cases

_MAX_PATCHES = 64


def _emit(ctx: ToolContext, event: dict[str, Any]) -> None:
    fn = ctx.extra.get("emit")
    if callable(fn):
        try:
            fn(event)
        except Exception:
            pass


def _dispatch(ctx: ToolContext, name: str, args: dict[str, Any]) -> ToolResult:
    mediator = ctx.extra.get("mediator")
    if mediator is None:
        return ToolResult.failure(
            "the modification engine needs the policy mediator; run it through the agent")
    return mediator.dispatch(name, args, ctx)


def _step(ctx: ToolContext, plan: ModificationPlan, step_id: str,
          status: str, detail: str | None = None) -> None:
    mark_step(plan, step_id, status)
    step = next((s for s in plan.steps if s.id == step_id), None)
    _emit(ctx, {
        "type": "modification_step",
        "step": step_id,
        "status": status,
        "title": step.title if step else step_id,
        "detail": detail if detail is not None else (step.detail if step else ""),
    })


def _has_sources(project_dir: str | None) -> bool:
    if not project_dir:
        return False
    base = Path(project_dir)
    if not base.is_dir():
        return False
    names = {"Makefile", "makefile", "CMakeLists.txt", "build.sh", "meson.build",
             "Cargo.toml", "pyproject.toml", "setup.py", "package.json", "go.mod"}
    try:
        for p in base.iterdir():
            if p.name in names:
                return True
            if p.suffix.lower() in {".c", ".cc", ".cpp", ".rs", ".go", ".py",
                                    ".java", ".kt", ".ts", ".tsx"}:
                return True
    except OSError:
        return False
    return False


def _cases_from_args(args: dict[str, Any]) -> list[InputCase]:
    raw: list[dict[str, Any]] = []
    for d in args.get("cases") or []:
        if isinstance(d, dict):
            raw.append(dict(d))
    for d in args.get("preserve_cases") or []:
        if isinstance(d, dict):
            d = dict(d)
            exp = dict(d.get("expect") or {})
            exp["same_as_original"] = True
            d["expect"] = exp
            raw.append(d)
    if raw:
        return [InputCase.from_dict(d).normalized() for d in raw]

    keys = {"args", "stdin", "stdin_b64", "files", "expect_stdout",
            "expect_stderr", "expect_exit", "expect_diff", "same_as_original",
            "stdout_contains", "stderr_contains", "output_files"}
    if any(k in args for k in keys):
        return build_cases(args)
    return []


def _encode_string(value: str) -> list[bytes]:
    out = [value.encode("utf-8")]
    if not value.isascii():
        out.append(value.encode("utf-16-le"))
    else:
        out.append(value.encode("utf-16-le"))
    return out


def _build_patches(target: str, report, args: dict[str, Any]) -> tuple[list[dict], str | None]:
    if args.get("patches"):
        patches = args["patches"]
        if not isinstance(patches, list) or len(patches) > _MAX_PATCHES:
            return [], f"patches must be a list of at most {_MAX_PATCHES} entries"
        return patches, None

    find_hex = args.get("find_hex")
    replace_hex = args.get("replace_hex")
    find = args.get("find")
    replace = args.get("replace", "")
    if not find_hex and not find:
        return [], ("tell me the exact bytes or text to replace, or provide a "
                    "patches list")

    data = read_target(target)
    start, end = 0, len(data)
    section_name = args.get("section")
    if section_name:
        section = next((s for s in report.sections if s.name == section_name), None)
        if section is None:
            return [], f"section not found: {section_name}"
        start = section.raw_offset
        end = min(len(data), start + max(section.raw_size, section.virtual_size))
        if start >= end:
            return [], f"section has no raw bytes: {section_name}"

    if find_hex:
        try:
            needle = bytes.fromhex(str(find_hex))
            replacement = bytes.fromhex(str(replace_hex or ""))
        except ValueError as exc:
            return [], f"bad hex: {exc}"
        enc = "hex"
    else:
        needle = b""
        replacement = b""
        enc = ""
        for candidate in _encode_string(str(find)):
            if candidate and candidate in data[start:end]:
                needle = candidate
                enc = "utf-16-le" if candidate[1:2] == b"\x00" else "utf-8"
                break
        if not needle:
            return [], f"could not find {find!r} in the target"
        replacement = str(replace or "").encode(enc)

    if not needle:
        return [], "empty search bytes"
    if len(replacement) > len(needle):
        return [], ("the replacement is longer than the matched bytes; an in-place "
                    "edit would shift the file. Use a rebuild or reimplementation.")
    replacement = replacement.ljust(len(needle), b"\x00")

    haystack = data[start:end]
    positions: list[int] = []
    cursor = 0
    while len(positions) < _MAX_PATCHES:
        pos = haystack.find(needle, cursor)
        if pos < 0:
            break
        positions.append(start + pos)
        cursor = pos + max(1, len(needle))
        if not args.get("replace_all"):
            break
    if not positions:
        return [], f"could not find {find!r} in the selected scope"
    occurrence = int(args.get("occurrence", 0) or 0)
    if not args.get("replace_all"):
        if occurrence < 0 or occurrence >= len(positions):
            return [], f"occurrence {occurrence} is out of range ({len(positions)} match(es))"
        positions = [positions[occurrence]]
    return [{
        "offset": pos,
        "hex": replacement.hex(),
        "expect_hex": needle.hex(),
    } for pos in positions], None


class ChooseModificationStrategyTool(Tool):
    name = "choose_modification_strategy"
    description = (
        "Inspect the target and recommend one modification strategy: resource_edit, "
        "byte_patch, component_replace, rebuild, or reimplement. Returns a plain "
        "rationale, score, confidence, alternatives, warnings, and a clarifying "
        "question when the evidence or request is too thin. Read-only."
    )
    parameters = {
        "type": "object",
        "properties": {
            "goal": {"type": "string",
                     "description": "the change the user wants"},
            "mode": {"type": "string",
                     "enum": ["direct", "reconstruction", "modernisation"]},
        },
        "required": ["goal"],
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        if not ctx.target_path:
            return ToolResult.failure("no target set for this job")
        goal = str(args.get("goal") or ctx.goal or "").strip()
        if not goal:
            return ToolResult.failure("missing 'goal'")
        try:
            report = analyze_file(ctx.target_path)
        except (OSError, ValidationError) as exc:
            return ToolResult.failure(f"could not analyze the target: {exc}")
        choice = choose_strategy(
            report, goal, mode=args.get("mode"),
            has_sources=_has_sources(ctx.extra.get("project_dir")))
        if ctx.evidence is not None:
            ctx.evidence.believed(
                f"recommended strategy: {choice.strategy} ({choice.mode}), "
                f"confidence {choice.confidence_label}",
                source=self.name, detail=choice.rationale)
        lines = [
            f"strategy: {choice.strategy} ({choice.label})",
            f"mode: {choice.mode} (recommended: {choice.recommended_mode})",
            f"confidence: {choice.confidence_label} ({choice.confidence:.0%})",
            f"why: {choice.rationale}",
        ]
        if choice.evidence:
            lines.append("evidence:")
            lines += [f"  - {e}" for e in choice.evidence]
        if choice.alternatives:
            lines.append("alternatives:")
            lines += [f"  - {a['strategy']} ({a['score']}): {a['note']}"
                      for a in choice.alternatives[:4]]
        if choice.warnings:
            lines.append("warnings:")
            lines += [f"  - {w}" for w in choice.warnings]
        if choice.needs_clarification:
            lines.append(f"clarification needed: {choice.question}")
        data = choice.to_dict()
        data["goal"] = goal
        return ToolResult(
            ok=not choice.needs_clarification,
            content="\n".join(lines),
            data=data,
            error="needs_clarification" if choice.needs_clarification else None,
        )


class PlanAndModifyTool(Tool):
    name = "plan_and_modify"
    description = (
        "Run the autonomous modification engine: choose a strategy, build an "
        "inspectable plan, scope the change, implement it on a copy through the "
        "existing executors, and prove it with the sandbox verify+repair loop. "
        "It asks for clarification instead of guessing when the request is "
        "ambiguous or no behavioral expectation is supplied. It never delivers an "
        "unverified artifact."
    )
    parameters = {
        "type": "object",
        "properties": {
            "goal": {"type": "string",
                     "description": "the natural-language change request"},
            "mode": {"type": "string",
                     "enum": ["direct", "reconstruction", "modernisation"],
                     "description": "optional user override; the engine recommends one"},
            "patches": {"type": "array", "items": {"type": "object"},
                        "description": "byte patches for a direct edit"},
            "find": {"type": "string",
                     "description": "text/bytes to replace in place"},
            "replace": {"type": "string"},
            "find_hex": {"type": "string"},
            "replace_hex": {"type": "string"},
            "section": {"type": "string",
                        "description": "limit a find/replace to one section"},
            "occurrence": {"type": "integer", "minimum": 0, "default": 0},
            "replace_all": {"type": "boolean", "default": False},
            "output_name": {"type": "string"},
            "cases": {"type": "array", "items": {"type": "object"},
                      "description": "intended-change cases with expectations"},
            "preserve_cases": {"type": "array", "items": {"type": "object"},
                               "description": "cases that must match the original"},
            "args": {"type": "array", "items": {"type": "string"}},
            "stdin": {"type": "string"},
            "expect_stdout": {"type": "string"},
            "expect_stderr": {"type": "string"},
            "expect_exit": {"type": "integer"},
            "expect_diff": {"type": "boolean"},
            "same_as_original": {"type": "boolean"},
            "max_attempts": {"type": "integer", "minimum": 1, "maximum": 10},
            "repair": {"type": "boolean", "default": True},
            "timeout_seconds": {"type": "number", "minimum": 0.1, "default": 10},
            "library": {"type": "string",
                        "description": "component_replace: add an imported library"},
            "functions": {"type": "array", "items": {"type": "string"}},
            "section_name": {"type": "string",
                             "description": "component_replace: add a section"},
            "content_hex": {"type": "string"},
            "rebuild_command": {"type": "array", "items": {"type": "string"}},
            "artifact": {"type": "string",
                         "description": "a rebuilt/reimplemented artifact to verify"},
            "project_dir": {"type": "string"},
        },
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        target = ctx.target_path
        if not target:
            return ToolResult.failure("no target set for this job")
        goal = str(args.get("goal") or ctx.goal or "").strip()
        if not goal:
            return ToolResult.failure("missing 'goal'")
        try:
            report = analyze_file(target)
        except (OSError, ValidationError) as exc:
            return ToolResult.failure(f"could not analyze the target: {exc}")

        mode = args.get("mode") or ctx.extra.get("mode") or ""
        project_dir = args.get("project_dir") or ctx.extra.get("project_dir")
        has_sources = _has_sources(project_dir)
        choice = choose_strategy(report, goal, mode=mode or None,
                                 has_sources=has_sources)
        ctx.extra["mode"] = choice.mode
        ctx.extra["strategy"] = choice.strategy

        try:
            cases = _cases_from_args(args)
        except DiffTestError as exc:
            return ToolResult.failure(f"bad modification cases: {exc}")
        has_preserve = bool(args.get("preserve_cases")) or any(
            (c.expect or {}).get("same_as_original") is True for c in cases)
        plan = build_plan(
            report, goal, choice, has_sources=has_sources,
            has_cases=bool(cases), has_preserve_cases=has_preserve)
        ctx.extra["modification_plan"] = plan.to_dict()
        _emit(ctx, {"type": "modification_plan", "plan": plan.to_dict()})

        def clarify(question: str) -> ToolResult:
            _step(ctx, plan, "locate", "pending")
            _emit(ctx, {"type": "reason", "tool": self.name,
                        "title": "One detail before changing anything",
                        "detail": question, "icon": "sparkle"})
            return ToolResult(ok=False, content=question, data=plan.to_dict(),
                              error="needs_clarification")

        if plan.needs_clarification:
            return clarify(plan.question)
        if not cases:
            return clarify(
                "What exact behavior should change? Give me at least one input and "
                "the expected output, or a cases list with expectations.")
        if plan.preserve_rest and not has_preserve:
            return clarify(
                "This is a scoped change. Which inputs represent the behavior that "
                "must stay unchanged? Add preserve_cases so I can prove the rest "
                "was not disturbed.")

        _step(ctx, plan, "investigate", "done")
        _step(ctx, plan, "locate", "done",
              ", ".join(f"{c.kind}:{c.name}" for c in plan.components[:8]))
        _step(ctx, plan, "impact", "done",
              f"{plan.blast_radius.level} risk: {plan.blast_radius.note}")
        _step(ctx, plan, "implement", "running")

        if choice.strategy in ("byte_patch", "resource_edit"):
            patches, err = _build_patches(target, report, args)
            if err:
                _step(ctx, plan, "implement", "failed", err)
                return ToolResult.failure(err)
            result = _dispatch(ctx, "apply_byte_patch", {
                "patches": patches,
                "output_name": args.get("output_name") or "",
            })
            if not result.ok:
                _step(ctx, plan, "implement", "failed", result.error or "")
                return result
        elif choice.strategy == "component_replace":
            if args.get("section_name") and args.get("content_hex"):
                result = _dispatch(ctx, "add_section", {
                    "name": args["section_name"],
                    "content_hex": args["content_hex"],
                })
            elif args.get("library"):
                result = _dispatch(ctx, "add_imported_library", {
                    "library": args["library"],
                    "functions": args.get("functions") or [],
                })
            else:
                _step(ctx, plan, "implement", "failed")
                return clarify(
                    "A component replacement needs either a library plus function "
                    "names, or a section name plus content bytes.")
            if not result.ok:
                _step(ctx, plan, "implement", "failed", result.error or "")
                return result
        elif choice.strategy == "rebuild":
            artifact = args.get("artifact")
            command = args.get("rebuild_command")
            if not artifact or not command:
                _step(ctx, plan, "implement", "failed")
                return clarify(
                    "A rebuild needs a build command and the resulting artifact path. "
                    "Provide rebuild_command and artifact, or choose a direct edit.")
            result = _dispatch(ctx, "run_command", {
                "argv": command,
                "timeout_seconds": args.get("timeout_seconds", 60),
            })
            if not result.ok or not Path(artifact).is_file():
                _step(ctx, plan, "implement", "failed",
                      result.error or f"artifact not found: {artifact}")
                return ToolResult.failure(
                    f"rebuild did not produce the artifact: {artifact}")
            ctx.extra["modified_path"] = str(Path(artifact).resolve())
            ctx.extra["modified_operation"] = "rebuild"
            ctx.extra["modified_turn"] = ctx.job_id
            ctx.extra["modified_label"] = "Rebuilt artifact"
        elif choice.strategy == "reimplement":
            artifact = args.get("artifact")
            if not artifact or not Path(artifact).is_file():
                _step(ctx, plan, "implement", "failed")
                return clarify(
                    "Reimplementation needs a built artifact to verify. Build the new "
                    "implementation and pass its path as artifact.")
            ctx.extra["modified_path"] = str(Path(artifact).resolve())
            ctx.extra["modified_operation"] = "reimplement"
            ctx.extra["modified_turn"] = ctx.job_id
            ctx.extra["modified_label"] = "Reimplemented artifact"
        else:
            _step(ctx, plan, "implement", "failed")
            return ToolResult.failure(f"unsupported strategy: {choice.strategy}")

        if not ctx.extra.get("modified_path"):
            _step(ctx, plan, "implement", "failed")
            return ToolResult.failure("no modified artifact was produced")
        _step(ctx, plan, "implement", "done")

        _step(ctx, plan, "verify", "running")
        verify_result = _dispatch(ctx, "verify_modification", {
            "cases": [c.to_dict() for c in cases],
            "max_attempts": args.get("max_attempts") or 3,
            "repair": bool(args.get("repair", True)),
            "timeout_seconds": args.get("timeout_seconds", 10),
        })
        verification = ctx.extra.get("verification") or {}
        delivery = ctx.extra.get("delivery") or {}
        ok = bool(verification.get("verified")) and bool(delivery.get("allowed"))
        _step(ctx, plan, "verify", "done" if ok else "failed",
              verification.get("reason", ""))
        ctx.extra["modification_plan"] = plan.to_dict()

        data = {
            "goal": goal,
            "strategy": choice.to_dict(),
            "plan": plan.to_dict(),
            "verification": verification,
            "delivery": delivery,
            "artifact": ctx.extra.get("modified_path"),
            "needs_clarification": False,
        }
        if ok:
            content = (
                f"Strategy: {choice.strategy} ({choice.label}), mode {choice.mode}.\n"
                f"{choice.rationale}\n\n"
                f"Plan: " + " -> ".join(s.title for s in plan.steps) + "\n"
                f"Verified: {verification.get('reason', 'behavioral test passed')}\n"
                f"Artifact: {ctx.extra.get('modified_path')}"
            )
            return ToolResult.success(content, **data)
        reason = verification.get("reason") or "the behavioral test did not pass"
        content = (
            f"Strategy: {choice.strategy} ({choice.label}), mode {choice.mode}.\n"
            f"The change was applied to a copy but is NOT verified: {reason}\n"
            "No artifact will be delivered. The reasoning timeline and report "
            "contain the failed attempts.")
        return ToolResult(ok=False, content=content, data=data, error=reason)
