"""General coding tools — the foundation for ReverseAI as a coding agent.

Reverse engineering is the flagship use, but the same agent writes and fixes
code too. These tools give it a scoped, safe view of a project directory:
list/read/write/edit files (contained to the project root, no traversal) and
run commands in the sandbox (network off, resource-limited) to build and test.

The project root is ``ctx.extra['project_dir']`` (falling back to the job
workspace). All paths are resolved through ``safe_join`` so nothing escapes it.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..security.validate import ValidationError, safe_join
from .tools import Permission, Tool, ToolContext, ToolResult

_MAX_READ_BYTES = 256 * 1024
_MAX_WRITE_BYTES = 2 * 1024 * 1024


def _project_root(ctx: ToolContext) -> Path:
    root = ctx.extra.get("project_dir") or ctx.workspace
    return Path(root)


def _resolve(ctx: ToolContext, rel: str) -> Path:
    return safe_join(_project_root(ctx), rel)


class ListDirTool(Tool):
    name = "list_dir"
    description = "List files and directories under a path within the project root."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "default": "."}},
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        try:
            base = _resolve(ctx, args.get("path", "."))
        except ValidationError as exc:
            return ToolResult.failure(str(exc))
        if not base.exists():
            return ToolResult.failure(f"no such path: {args.get('path', '.')}")
        if base.is_file():
            return ToolResult.success(f"{base.name} (file, {base.stat().st_size} bytes)")
        root = _project_root(ctx)
        entries = []
        for p in sorted(base.iterdir()):
            kind = "dir" if p.is_dir() else "file"
            rel = p.relative_to(root)
            size = "" if p.is_dir() else f" {p.stat().st_size}b"
            entries.append(f"{kind:4} {rel}{size}")
        return ToolResult.success("\n".join(entries) or "(empty)", count=len(entries))


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a UTF-8 text file within the project root."
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        try:
            p = _resolve(ctx, args["path"])
        except ValidationError as exc:
            return ToolResult.failure(str(exc))
        if not p.is_file():
            return ToolResult.failure(f"not a file: {args['path']}")
        if p.stat().st_size > _MAX_READ_BYTES:
            return ToolResult.failure(f"file too large to read (> {_MAX_READ_BYTES} bytes)")
        text = p.read_text("utf-8", "replace")
        numbered = "\n".join(f"{i+1}\t{line}" for i, line in enumerate(text.splitlines()))
        return ToolResult.success(numbered, path=args["path"], lines=text.count("\n") + 1)


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Create or overwrite a UTF-8 text file within the project root. Creates "
        "parent directories as needed. For a large file, write a short skeleton "
        "first, then append sections with append=true. Keep each call small "
        "enough to finish inside one model response."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
            "append": {
                "type": "boolean",
                "default": False,
                "description": "append instead of overwriting; creates the file if absent",
            },
        },
        "required": ["path", "content"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        content = args["content"]
        if len(content.encode("utf-8")) > _MAX_WRITE_BYTES:
            return ToolResult.failure("content exceeds write size limit")
        try:
            p = _resolve(ctx, args["path"])
        except ValidationError as exc:
            return ToolResult.failure(str(exc))
        p.parent.mkdir(parents=True, exist_ok=True)
        existed = p.exists()
        if args.get("append"):
            with p.open("a", encoding="utf-8") as fh:
                fh.write(content)
            action = "appended to" if existed else "created"
        else:
            p.write_text(content, "utf-8")
            action = "overwrote" if existed else "created"
        return ToolResult.success(
            f"{action} {args['path']} ({len(content)} chars)",
            path=args["path"], created=not existed)


class EditFileTool(Tool):
    name = "edit_file"
    description = (
        "Replace an exact substring in a file within the project root. "
        "`old` must occur exactly once unless `all` is true."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
            "all": {"type": "boolean", "default": False},
        },
        "required": ["path", "old", "new"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        try:
            p = _resolve(ctx, args["path"])
        except ValidationError as exc:
            return ToolResult.failure(str(exc))
        if not p.is_file():
            return ToolResult.failure(f"not a file: {args['path']}")
        text = p.read_text("utf-8", "replace")
        old = args["old"]
        count = text.count(old)
        if count == 0:
            return ToolResult.failure("`old` string not found")
        if count > 1 and not args.get("all"):
            return ToolResult.failure(
                f"`old` occurs {count} times; pass all=true or make it unique")
        text = text.replace(old, args["new"], -1 if args.get("all") else 1)
        p.write_text(text, "utf-8")
        return ToolResult.success(f"edited {args['path']} ({count if args.get('all') else 1} "
                                  "replacement(s))")


class RunCommandTool(Tool):
    name = "run_command"
    description = (
        "Run a build/test/shell command in the sandbox with the project mounted "
        "read-write. Network is off unless the operator enabled it, and the "
        "command is time- and resource-limited. Returns exit code, stdout, and stderr."
    )
    parameters = {
        "type": "object",
        "properties": {
            "argv": {"type": "array", "items": {"type": "string"},
                     "description": "command and arguments, e.g. [\"python3\",\"-m\",\"pytest\"]"},
            "timeout_seconds": {"type": "number", "minimum": 0.1, "default": 30},
        },
        "required": ["argv"],
    }
    permission = Permission.EXECUTE

    def run(self, args, ctx) -> ToolResult:
        from dataclasses import replace

        from ..sandbox import SandboxPolicy, SandboxUnavailable, create_sandbox

        argv = [str(a) for a in args.get("argv", [])]
        if not argv:
            return ToolResult.failure("argv must be non-empty")

        root = str(_project_root(ctx))
        base = ctx.sandbox_policy or SandboxPolicy()
        policy = replace(
            base,
            workdir=root,
            rw_binds=list(base.rw_binds) + [root],
            # Network egress is an operator decision, never a model decision.
            allow_network=os.environ.get("REVERSEAI_ALLOW_CODING_NETWORK") == "1",
            timeout_seconds=min(max(float(args.get("timeout_seconds", 30)), 0.1), 300.0),
            # allow reasonable PATH for dev tools
            env={**base.env, "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": root},
        )
        try:
            sb = create_sandbox(policy)
        except SandboxUnavailable as exc:
            return ToolResult.failure(str(exc))
        res = sb.run(argv, policy, cwd=root)
        summary = (
            f"$ {' '.join(argv)}\n"
            f"[{sb.name}] exit={res.exit_code} signal={res.term_signal} "
            f"timed_out={res.timed_out} ({res.duration_s:.2f}s)\n"
            f"--- stdout ---\n{res.stdout_text()[:6000]}\n"
            f"--- stderr ---\n{res.stderr_text()[:3000]}"
        )
        return ToolResult(ok=not res.error and res.exit_code == 0,
                          content=summary, data=res.to_dict(), error=res.error)


def coding_tools() -> list[Tool]:
    return [ListDirTool(), ReadFileTool(), WriteFileTool(), EditFileTool(), RunCommandTool()]
