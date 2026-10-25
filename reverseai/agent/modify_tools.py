"""Modification + verification tools (WRITE / EXECUTE tiers).

Exposed to the agent only when the job's permission ceiling allows WRITE, so a
read/execute-only investigation can never mutate anything. All edits land on a
copy in the job workspace; the original is never touched.
"""

from __future__ import annotations

from pathlib import Path

from ..modify import BytePatch, PatchError, apply_byte_patches
from ..naming import artifact_name
from ..verify import compare_execution
from .tools import Permission, Tool, ToolContext, ToolResult


def _require_target(ctx: ToolContext) -> str:
    if not ctx.target_path:
        raise PatchError("no target set for this job")
    return ctx.target_path


def _invalidate_verification(ctx: ToolContext) -> None:
    """A new candidate invalidates every prior test and delivery decision."""
    for key in ("verification", "delivery", "differential"):
        ctx.extra.pop(key, None)


def _auto_checkpoint(ctx: ToolContext, label: str) -> str | None:
    """Snapshot the workspace before a write, so the change is reversible."""
    store = ctx.extra.get("checkpoint_store")
    if store is None:
        return None
    try:
        cp = store.create(label=label, note="automatic pre-modification snapshot")
        ctx.extra["last_checkpoint"] = cp.id
        return cp.id
    except Exception:
        # A failed snapshot must not block the operation, but it is recorded.
        return None


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
            "output_name": {"type": "string",
                            "description": "name for the delivered file (with extension)"},
        },
        "required": ["patches"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        from pathlib import Path

        target = _require_target(ctx)
        if len(args["patches"]) > 1000:
            return ToolResult.failure("too many patches in one request (max 1000)")
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

        # Descriptive, unique output name: "<stem>-patched-<intent>-<token>".
        tp = Path(target)
        _auto_checkpoint(ctx, f"before patch: {Path(target).name}")
        out_name = args.get("output_name") or artifact_name(
            target, ctx.goal, "patch", suffix=tp.suffix)
        try:
            result = apply_byte_patches(target, patches, ctx.workspace, out_name=out_name)
        except PatchError as exc:
            return ToolResult.failure(str(exc))

        _invalidate_verification(ctx)
        ctx.extra["modified_path"] = result.output_path
        ctx.extra["modified_operation"] = "patch"
        ctx.extra["modified_label"] = "Patched copy"
        ctx.extra["modified_turn"] = ctx.job_id
        ctx.extra["last_patches"] = result.details
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
        "arguments and compare exit status and output. This is a comparison only: "
        "it records an observation and does NOT authorize delivery. Use "
        "verify_modification with a declared expectation to prove the change."
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
                "no modified artifact yet - run apply_byte_patch first")

        base = ctx.sandbox_policy or SandboxPolicy()
        timeout = min(max(float(args.get("timeout_seconds", base.timeout_seconds)), 0.1), 120.0)
        policy = replace(base, timeout_seconds=timeout)
        report = compare_execution(target, modified, args.get("args", []), policy)
        if not report.ran:
            return ToolResult.failure(f"verification could not run: {report.error}")

        if ctx.evidence is not None:
            # This proves a comparison ran; it does not prove the intended
            # change. Only verify_modification may add a verified claim.
            ctx.evidence.observed(f"behavioral comparison: {report.verdict}",
                                  source=self.name)

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
        "(sections, imports, exports, size, entropy). It shows WHAT changed "
        "statically; verify_modification proves whether the change works. "
        "Requires a modified artifact first."
    )
    parameters = {"type": "object", "properties": {}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from ..core.diff import diff_files

        target = _require_target(ctx)
        modified = ctx.extra.get("modified_path")
        if not modified:
            return ToolResult.failure("no modified artifact yet - apply a patch first")
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
        _auto_checkpoint(ctx, f"before import: {args['library']}")
        out_name = artifact_name(target, ctx.goal, "imports",
                                 suffix=Path(target).suffix)
        try:
            out = add_imported_library(target, ctx.workspace, args["library"],
                                       args.get("functions"), out_name=out_name)
        except (LiefUnavailable, LiefOpError) as exc:
            return ToolResult.failure(str(exc))
        _invalidate_verification(ctx)
        ctx.extra["modified_path"] = out
        ctx.extra["modified_operation"] = "imports"
        ctx.extra["modified_turn"] = ctx.job_id
        ctx.extra["modified_label"] = f"Added import {args['library']}"
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
        _auto_checkpoint(ctx, f"before section: {args.get('name', 'section')}")
        try:
            content = bytes.fromhex(args["content_hex"])
        except ValueError as exc:
            return ToolResult.failure(f"bad content_hex: {exc}")
        out_name = artifact_name(target, ctx.goal, "section",
                                 suffix=Path(target).suffix)
        try:
            out = add_section(target, ctx.workspace, args["name"], content,
                              out_name=out_name)
        except (LiefUnavailable, LiefOpError) as exc:
            return ToolResult.failure(str(exc))
        _invalidate_verification(ctx)
        ctx.extra["modified_path"] = out
        ctx.extra["modified_operation"] = "section"
        ctx.extra["modified_turn"] = ctx.job_id
        ctx.extra["modified_label"] = f"Added section {args['name']}"
        return ToolResult.success(f"wrote {out} with section {args['name']}",
                                  output_path=out)


class ExtractArchiveTool(Tool):
    name = "extract_archive"
    description = (
        "Safely extract an archive target (zip/tar/tar.gz/…) into the workspace "
        "with decompression-bomb and path-traversal protection. If the archive "
        "looks like a bomb, extraction is refused and reported — it never takes "
        "the system down. Use before analyzing the contents of a dropped archive."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string",
                     "description": "archive path; defaults to the target"},
        },
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        from pathlib import Path

        from ..security.archive import ArchiveError, BombDetected, safe_extract

        src = args.get("path") or ctx.target_path
        if not src:
            return ToolResult.failure("no archive path")
        dest = str(Path(ctx.workspace) / "extracted")
        try:
            res = safe_extract(src, dest)
        except BombDetected as exc:
            if ctx.evidence is not None:
                ctx.evidence.observed(f"archive refused as bomb: {exc}", source=self.name)
            return ToolResult.failure(
                f"refused: decompression bomb detected ({exc}). Nothing was "
                "extracted; the system is unaffected.")
        except (ArchiveError, OSError) as exc:
            return ToolResult.failure(f"extraction failed: {exc}")
        ctx.extra["extracted_dir"] = res.dest
        preview = ", ".join(res.members[:12])
        return ToolResult.success(
            f"extracted {res.files} files ({res.total_bytes} bytes) to {res.dest}\n"
            f"members: {preview}", **res.to_dict())


class CloneWebsiteTool(Tool):
    name = "clone_website"
    description = (
        "Clone a public website into a self-contained static folder: fetch the "
        "page and its same-origin assets (CSS/JS/images/fonts), rewrite links to "
        "local copies, and optionally rename a brand throughout. Produces an "
        "offline-renderable replica of the front-end (exact markup, styling, and "
        "CSS/JS animations) delivered as a zip. It does NOT reproduce the server "
        "behind the site. Refuses non-public/internal hosts."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "the page URL to clone"},
            "rename_from": {"type": "string", "description": "brand text to replace"},
            "rename_to": {"type": "string", "description": "new brand text"},
            "output_name": {"type": "string",
                            "description": "name for the delivered file (no extension)"},
        },
        "required": ["url"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        import shutil
        from pathlib import Path

        from ..clone import CloneError, clone_best

        site_dir = Path(ctx.workspace) / "clone"
        try:
            res = clone_best(args["url"], site_dir,
                             rename_from=args.get("rename_from"),
                             rename_to=args.get("rename_to"))
        except (CloneError, OSError) as exc:
            return ToolResult.failure(f"clone failed: {exc}")

        # Package the replica with a meaningful, unique name.
        import urllib.parse
        parsed = urllib.parse.urlparse(args["url"])
        label = args.get("output_name") or args.get("rename_to") \
            or parsed.hostname or "site"
        name = args.get("output_name") or artifact_name(
            label, ctx.goal, "site", suffix="")
        if name.lower().endswith(".zip"):
            name = name[:-4]
        base = Path(ctx.workspace) / name
        zip_path = shutil.make_archive(str(base), "zip", str(site_dir))
        _invalidate_verification(ctx)
        ctx.extra["modified_path"] = zip_path
        ctx.extra["modified_operation"] = "site"
        ctx.extra["modified_turn"] = ctx.job_id
        ctx.extra["modified_label"] = "Offline site bundle"
        if ctx.evidence is not None:
            ctx.evidence.verified(
                f"cloned {args['url']}: {res.pages} page, {res.assets} assets, "
                f"{res.renamed} renames", source=self.name)
        summary = (
            f"cloned {args['url']}\n"
            f"assets: {res.assets}  bytes: {res.total_bytes}  renames: {res.renamed}\n"
            f"packaged: {zip_path}"
        )
        if res.skipped:
            summary += f"\nskipped (off-site/failed): {len(res.skipped)}"
        return ToolResult.success(summary, **res.to_dict(), zip=zip_path)


def modification_tools() -> list[Tool]:
    tools: list[Tool] = [
        ApplyBytePatchTool(), VerifyAgainstOriginalTool(), StructuralDiffTool(),
        ExtractArchiveTool(), CloneWebsiteTool(),
    ]
    # LIEF-backed structural edits only when the library is present.
    from ..modify.lief_ops import lief_available

    if lief_available():
        tools += [AddImportTool(), AddSectionTool()]
    return tools

