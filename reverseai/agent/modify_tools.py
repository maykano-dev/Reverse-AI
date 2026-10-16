"""Modification + verification tools (WRITE / EXECUTE tiers).

Exposed to the agent only when the job's permission ceiling allows WRITE, so a
read/execute-only investigation can never mutate anything. All edits land on a
copy in the job workspace; the original is never touched.
"""

from __future__ import annotations

from ..modify import BytePatch, PatchError, apply_byte_patches
from ..verify import compare_execution
from .evidence import Confidence
from .tools import Permission, Tool, ToolContext, ToolResult


def _require_target(ctx: ToolContext) -> str:
    if not ctx.target_path:
        raise PatchError("no target set for this job")
    return ctx.target_path


class ApplyBytePatchTool(Tool):
    name = "apply_byte_patch"
    description = (
        "Apply one or more byte patches to a COPY of the target (the original is "
        "never modified) and save it in the job workspace. Each patch gives a "
        "file offset and replacement bytes as hex; optionally assert the current "
        "bytes with 'expect_hex' so the patch cannot hit the wrong location. The "
        "resulting file becomes the modified artifact for verification."
    )
    parameters = {
        "type": "object",
        "properties": {
            "patches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "offset": {"type": "integer", "minimum": 0},
                        "hex": {"type": "string", "description": "replacement bytes as hex"},
                        "expect_hex": {"type": "string",
                                       "description": "optional: bytes expected at offset"},
                    },
                    "required": ["offset", "hex"],
                },
                "minItems": 1,
            },
        },
        "required": ["patches"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        target = _require_target(ctx)
        try:
            patches = [
                BytePatch(
                    offset=int(p["offset"]),
                    data=bytes.fromhex(p["hex"]),
                    expected_original=bytes.fromhex(p["expect_hex"]) if p.get("expect_hex") else None,
                )
                for p in args["patches"]
            ]
        except (ValueError, KeyError) as exc:
            return ToolResult.failure(f"bad patch spec: {exc}")

        try:
            result = apply_byte_patches(target, patches, ctx.workspace)
        except PatchError as exc:
            return ToolResult.failure(str(exc))

        ctx.extra["modified_path"] = result.output_path
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"applied {result.patches_applied} patch(es), "
                f"{result.bytes_changed} bytes changed; "
                f"sha256 {result.original_sha256[:12]} -> {result.modified_sha256[:12]}",
                source=self.name,
            )
        summary = (
            f"wrote modified copy: {result.output_path}\n"
            f"original sha256: {result.original_sha256}\n"
            f"modified sha256: {result.modified_sha256}\n"
            f"patches: {result.patches_applied}  bytes changed: {result.bytes_changed}"
        )
        return ToolResult.success(summary, **result.to_dict())


class VerifyAgainstOriginalTool(Tool):
    name = "verify_against_original"
    description = (
        "Run the original and the modified binary in the sandbox with the same "
        "arguments and compare exit status and output. Use this to prove whether "
        "a modification achieved the intended change without breaking existing "
        "behavior. Requires a modified artifact from apply_byte_patch first."
    )
    parameters = {
        "type": "object",
        "properties": {
            "args": {"type": "array", "items": {"type": "string"}},
            "timeout_seconds": {"type": "number", "minimum": 0.1, "default": 10},
        },
    }
    permission = Permission.EXECUTE

    def run(self, args, ctx) -> ToolResult:
        from dataclasses import replace

        from ..sandbox import SandboxPolicy

        target = _require_target(ctx)
        modified = ctx.extra.get("modified_path")
        if not modified:
            return ToolResult.failure(
                "no modified artifact yet — run apply_byte_patch first")

        base = ctx.sandbox_policy or SandboxPolicy()
        policy = replace(base, timeout_seconds=float(
            args.get("timeout_seconds", base.timeout_seconds)))
        report = compare_execution(target, modified, args.get("args", []), policy)
        if not report.ran:
            return ToolResult.failure(f"verification could not run: {report.error}")

        if ctx.evidence is not None:
            ctx.evidence.verified(f"regression: {report.verdict}", source=self.name)

        o, m = report.original, report.modified
        summary = (
            f"verdict: {report.verdict}\n"
            f"original: exit={o.exit_code} signal={o.term_signal} "
            f"timed_out={o.timed_out}\n"
            f"modified: exit={m.exit_code} signal={m.term_signal} "
            f"timed_out={m.timed_out}\n"
            f"same_exit={report.same_exit} same_stdout={report.same_stdout} "
            f"same_stderr={report.same_stderr}"
        )
        if report.notes:
            summary += "\nnotes: " + "; ".join(report.notes)
        return ToolResult.success(summary, **report.to_dict())


class StructuralDiffTool(Tool):
    name = "diff_modified"
    description = (
        "Structurally compare the original target with the modified artifact "
        "(sections, imports, exports, size, entropy). Pairs with "
        "verify_against_original: this shows WHAT changed statically, that shows "
        "whether behavior changed. Requires a modified artifact first."
    )
    parameters = {"type": "object", "properties": {}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from ..core.diff import diff_files

        target = _require_target(ctx)
        modified = ctx.extra.get("modified_path")
        if not modified:
            return ToolResult.failure("no modified artifact yet — run apply_byte_patch first")
        d = diff_files(target, modified)
        return ToolResult.success(f"diff: {d.summary}", **d.to_dict())


class AddImportTool(Tool):
    name = "add_imported_library"
    description = (
        "Add an imported library (and optional functions) to a PE binary using "
        "LIEF, writing a modified copy. Experimental structural edit toward "
        "adding capability. Requires LIEF installed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "library": {"type": "string"},
            "functions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["library"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        from ..modify.lief_ops import LiefOpError, LiefUnavailable, add_imported_library

        target = _require_target(ctx)
        try:
            out = add_imported_library(target, ctx.workspace, args["library"],
                                       args.get("functions"))
        except (LiefUnavailable, LiefOpError) as exc:
            return ToolResult.failure(str(exc))
        ctx.extra["modified_path"] = out
        if ctx.evidence is not None:
            ctx.evidence.observed(f"added import {args['library']}", source=self.name)
        return ToolResult.success(f"wrote {out} with import {args['library']}",
                                  output_path=out)


class AddSectionTool(Tool):
    name = "add_section"
    description = (
        "Add a new named section with given content (hex) to the binary using "
        "LIEF, writing a modified copy. Requires LIEF installed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "content_hex": {"type": "string"},
        },
        "required": ["name", "content_hex"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        from ..modify.lief_ops import LiefOpError, LiefUnavailable, add_section

        target = _require_target(ctx)
        try:
            content = bytes.fromhex(args["content_hex"])
        except ValueError as exc:
            return ToolResult.failure(f"bad content_hex: {exc}")
        try:
            out = add_section(target, ctx.workspace, args["name"], content)
        except (LiefUnavailable, LiefOpError) as exc:
            return ToolResult.failure(str(exc))
        ctx.extra["modified_path"] = out
        return ToolResult.success(f"wrote {out} with section {args['name']}",
                                  output_path=out)


def modification_tools() -> list[Tool]:
    tools: list[Tool] = [
        ApplyBytePatchTool(), VerifyAgainstOriginalTool(), StructuralDiffTool(),
    ]
    # LIEF-backed structural edits only when the library is present.
    from ..modify.lief_ops import lief_available

    if lief_available():
        tools += [AddImportTool(), AddSectionTool()]
    return tools

