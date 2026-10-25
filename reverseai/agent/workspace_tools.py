"""Workspace checkpoints, undo, diff review, and execution readiness.

These tools make the agent's writes reversible and make the limits of execution
explicit before a change is promised. They never touch the host outside the job
workspace.
"""

from __future__ import annotations

from ..checkpoints import CheckpointError, CheckpointStore
from ..sandbox.readiness import assess_execution
from .tools import Permission, Tool, ToolContext, ToolResult


def _store(ctx: ToolContext) -> CheckpointStore:
    store = ctx.extra.get("checkpoint_store")
    if store is not None:
        return store
    return CheckpointStore(_default_dir(ctx), workspace=ctx.workspace)


def _default_dir(ctx: ToolContext) -> str:
    import os
    from pathlib import Path

    base = os.environ.get("REVERSEAI_STORE", "").strip()
    root = Path(base) if base else Path(ctx.workspace).parent
    return str(root / "checkpoints" / Path(ctx.workspace).name)


def _latest(ctx: ToolContext, store: CheckpointStore) -> str | None:
    items = store.list()
    return items[0].id if items else None


class CreateCheckpointTool(Tool):
    name = "create_workspace_checkpoint"
    description = (
        "Snapshot the job workspace (files and hashes) before a risky change. "
        "Returns a checkpoint id that can be reviewed or restored. Symlinks and "
        "paths outside the workspace are never included."
    )
    parameters = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "default": "checkpoint"},
            "note": {"type": "string"},
        },
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        try:
            cp = _store(ctx).create(str(args.get("label") or "checkpoint"),
                                    str(args.get("note") or ""))
        except CheckpointError as exc:
            return ToolResult.failure(str(exc))
        ctx.extra["last_checkpoint"] = cp.id
        return ToolResult.success(
            f"checkpoint {cp.id}: {len(cp.files)} file(s), {cp.label}",
            checkpoint=cp.to_dict())


class ListCheckpointsTool(Tool):
    name = "list_workspace_checkpoints"
    description = "List workspace checkpoints, newest first."
    parameters = {"type": "object", "properties": {}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        try:
            items = [c.to_dict() for c in _store(ctx).list()]
        except CheckpointError as exc:
            return ToolResult.failure(str(exc))
        if not items:
            return ToolResult.success("No workspace checkpoints yet.", checkpoints=[])
        lines = [f"{c['id']}  {c['label']}  ({len(c['files'])} files)"
                 for c in items[:20]]
        return ToolResult.success("\n".join(lines), checkpoints=items[:20])


class ReviewWorkspaceChangesTool(Tool):
    name = "review_workspace_changes"
    description = (
        "Show what changed in the workspace since a checkpoint (or the newest "
        "one): added, removed, changed files and a bounded unified diff. Read-only."
    )
    parameters = {
        "type": "object",
        "properties": {"checkpoint": {"type": "string"}},
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        store = _store(ctx)
        cid = str(args.get("checkpoint") or "").strip() or _latest(ctx, store)
        if not cid:
            return ToolResult.failure("no checkpoint found; create one first")
        try:
            diff = store.review(cid)
        except CheckpointError as exc:
            return ToolResult.failure(str(exc))
        body = [f"checkpoint {cid}: {diff['summary']}"]
        if diff.get("diff"):
            body.append(diff["diff"])
        else:
            body.append("No file content changes.")
        return ToolResult.success("\n".join(body), **diff)


class RestoreCheckpointTool(Tool):
    name = "restore_workspace_checkpoint"
    description = (
        "Restore files from a workspace checkpoint. Refuses to overwrite existing "
        "files unless overwrite=true. Never extracts symlinks or paths outside "
        "the workspace."
    )
    parameters = {
        "type": "object",
        "properties": {
            "checkpoint": {"type": "string"},
            "overwrite": {"type": "boolean", "default": False},
        },
        "required": ["checkpoint"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        try:
            result = _store(ctx).restore(str(args["checkpoint"]),
                                         overwrite=bool(args.get("overwrite")))
        except CheckpointError as exc:
            return ToolResult.failure(str(exc))
        ctx.extra["modified_path"] = None
        ctx.extra.pop("verification", None)
        ctx.extra.pop("delivery", None)
        return ToolResult.success(result["summary"], **result)


class CheckExecutionReadinessTool(Tool):
    name = "check_execution_readiness"
    description = (
        "Before promising a verified change, report whether the target can run "
        "natively on this host under an isolating sandbox. A PE/Mach-O or foreign "
        "architecture target is analysis-only unless an emulator with a rootfs is "
        "configured. Read-only."
    )
    parameters = {"type": "object", "properties": {}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        if not ctx.target_path:
            return ToolResult.failure("no target set for this job")
        result = assess_execution(ctx.target_path, ctx.sandbox_policy)
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"execution readiness: {result.verdict} ({result.reason})",
                source=self.name)
        body = (f"verdict: {result.verdict}\n"
                f"reason: {result.reason}\n"
                f"backend: {result.backend} (level {result.level})")
        if result.suggestions:
            body += "\n" + "\n".join(f"- {s}" for s in result.suggestions)
        return ToolResult(ok=result.verdict in ("executable", "emulated"),
                          content=body, data=result.to_dict(),
                          error=None if result.verdict in ("executable", "emulated")
                          else "analysis_only")
