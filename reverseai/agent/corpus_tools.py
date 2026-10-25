"""Agent tool for capturing durable behavioral regression corpora."""

from __future__ import annotations

from typing import Any

from ..verify.corpus import (
    CorpusError,
    CorpusStore,
    capture_corpus,
    default_corpus_dir,
    target_sha256,
)
from ..verify.difftest import DiffTestError, InputCase, generate_corpus
from .tools import Permission, Tool, ToolContext, ToolResult


class CaptureBehaviorCorpusTool(Tool):
    name = "capture_behavior_corpus"
    description = (
        "Run the original target over a set of safe inputs in the sandbox and "
        "store its exit/stdout/stderr/output-file behavior as a durable regression "
        "corpus keyed by target SHA-256. Later changes can be verified with "
        "use_corpus, so an unrelated behavior change is caught automatically. "
        "This does not modify the target and does not authorize delivery."
    )
    parameters = {
        "type": "object",
        "properties": {
            "cases": {"type": "array", "items": {"type": "object"},
                      "description": "targeted inputs; auto-generated when omitted"},
            "output_files": {"type": "array", "items": {"type": "string"},
                             "description": "output files to capture"},
            "timeout_seconds": {"type": "number", "minimum": 0.1, "default": 10},
            "goal": {"type": "string"},
        },
    }
    permission = Permission.EXECUTE

    def run(self, args, ctx) -> ToolResult:
        if not ctx.target_path:
            return ToolResult.failure("no target set for this job")
        try:
            if args.get("cases"):
                cases = [InputCase.from_dict(d).normalized()
                         for d in args["cases"] if isinstance(d, dict)]
            else:
                cases = generate_corpus()
        except DiffTestError as exc:
            return ToolResult.failure(f"bad corpus case: {exc}")
        if not cases:
            return ToolResult.failure("empty corpus")

        store = ctx.extra.get("corpus_store")
        if store is None:
            store = CorpusStore(default_corpus_dir())
        try:
            captured, summary = capture_corpus(
                ctx.target_path, cases,
                policy=ctx.sandbox_policy,
                output_files=[str(x) for x in args.get("output_files") or []],
                timeout_seconds=min(max(float(args.get("timeout_seconds", 10)), 0.1), 60),
            )
            sha = target_sha256(ctx.target_path)
            path = store.save(sha, captured, goal=args.get("goal") or ctx.goal,
                              source=self.name)
        except CorpusError as exc:
            return ToolResult.failure(str(exc))
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"captured {len(captured)} regression case(s) for target "
                f"{sha[:12]}", source=self.name,
                detail="The original behavior is now a reusable corpus.")
        body = (
            f"Captured {len(captured)} regression case(s) for {sha[:12]}.\n"
            f"Stored at {path}\n"
            f"{summary.get('summary', '')}"
        )
        return ToolResult.success(
            body, target_sha256=sha, cases=len(captured),
            path=str(path), summary=summary,
            corpus=[c.to_dict() for c in captured])


def corpus_cases_for(ctx: ToolContext, args: dict[str, Any]) -> list[InputCase]:
    """Load stored regression cases for the current target, if requested."""
    if not args.get("use_corpus"):
        return []
    from ..verify.corpus import load_for_target

    store = ctx.extra.get("corpus_store")
    if store is None:
        store = CorpusStore(default_corpus_dir())
    return load_for_target(
        store, ctx.target_path or "",
        exclude=[str(x) for x in args.get("corpus_exclude") or []],
        prefix="corpus")
