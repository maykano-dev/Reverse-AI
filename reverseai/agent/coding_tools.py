"""General coding tools — the foundation for ReverseAI as a coding agent.

Reverse engineering is the flagship use, but the same agent writes and fixes
code too. These tools give it a scoped, safe view of a project directory:
list/read/write/edit files (contained to the project root, no traversal) and
run commands in the sandbox (network off, resource-limited) to build and test.

The project root is ``ctx.extra['project_dir']`` (falling back to the job
workspace). All paths are resolved through ``safe_join`` so nothing escapes it.
"""

from __future__ import annotations

import mimetypes
import os
import re
import urllib.parse
from pathlib import Path

from ..preview import preview_entry
from ..security.net import NetworkError, fetch as safe_fetch
from ..security.validate import ValidationError, safe_join
from .tools import Permission, Tool, ToolContext, ToolResult

_MAX_READ_BYTES = 256 * 1024
_MAX_WRITE_BYTES = 2 * 1024 * 1024
_MAX_MEDIA_BYTES = 15 * 1024 * 1024
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif", ".ico"}
_MIME_EXT = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
    "image/gif": ".gif", "image/svg+xml": ".svg", "image/avif": ".avif",
    "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico",
}


def _looks_like_image(data: bytes, ext: str) -> bool:
    head = data[:512]
    if ext == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == ".gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if ext == ".webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ext == ".avif":
        return b"ftypavif" in head[:32] or b"ftypavis" in head[:32]
    if ext == ".ico":
        return head.startswith(b"\x00\x00\x01\x00")
    if ext == ".svg":
        text = head.lstrip().lower()
        return b"<svg" in text or (text.startswith(b"<?xml") and b"<svg" in data[:4096].lower())
    return False


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


class InstallMediaTool(Tool):
    name = "install_media"
    description = (
        "Install a real image into the generated site. Accepts an uploaded file "
        "path (shown as an attachment) or a public http(s) image URL. It validates "
        "the image, copies it under the site's assets folder, and returns the "
        "relative src to use in HTML. Use this instead of saying you cannot add "
        "images, and never substitute fabricated photos for real ones."
    )
    parameters = {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "uploaded file path or a public image URL",
            },
            "name": {"type": "string", "description": "optional output filename"},
            "dest": {
                "type": "string",
                "description": "optional workspace-relative directory (default: "
                               "the site's assets folder)",
            },
            "alt": {"type": "string", "description": "optional alt text"},
        },
        "required": ["source"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        source = str(args.get("source") or "").strip()
        if not source:
            return ToolResult.failure("source is required")
        root = _project_root(ctx).resolve()
        name = str(args.get("name") or "").strip()
        mime = ""
        if source.lower().startswith(("http://", "https://")):
            try:
                data, mime, final = safe_fetch(
                    source, max_bytes=_MAX_MEDIA_BYTES, timeout=20.0,
                    accept="image/avif,image/webp,image/png,image/jpeg,image/*")
            except NetworkError as exc:
                return ToolResult.failure(f"could not fetch image: {exc}")
            if not name:
                name = Path(urllib.parse.urlparse(final).path).name
        else:
            p = Path(source)
            if not p.is_absolute():
                p = root / p
            p = p.resolve()
            allowed = [root]
            upload_root = ctx.extra.get("upload_root")
            if upload_root:
                allowed.append(Path(upload_root).resolve())
            if not any(p == a or a in p.parents for a in allowed):
                return ToolResult.failure(
                    "source must be an uploaded file or inside the project")
            try:
                if not p.is_file():
                    return ToolResult.failure(f"no such image: {source}")
                if p.stat().st_size > _MAX_MEDIA_BYTES:
                    return ToolResult.failure("image exceeds the 15 MiB limit")
                data = p.read_bytes()
            except OSError as exc:
                return ToolResult.failure(f"could not read image: {exc}")
            mime = mimetypes.guess_type(p.name)[0] or ""
            if not name:
                name = p.name
        if not data:
            return ToolResult.failure("image is empty")
        if len(data) > _MAX_MEDIA_BYTES:
            return ToolResult.failure("image exceeds the 15 MiB limit")
        ext = Path(name).suffix.lower()
        if ext not in _IMAGE_EXTS:
            ext = _MIME_EXT.get(mime.split(";", 1)[0].lower(), "")
        if not ext:
            return ToolResult.failure("unsupported image type")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).name).strip("-.") or "image"
        if Path(safe).suffix.lower() not in _IMAGE_EXTS:
            safe += ext
        if not _looks_like_image(data, Path(safe).suffix.lower()):
            return ToolResult.failure("file does not look like the claimed image type")

        entry = preview_entry(root)
        if args.get("dest"):
            target_dir = _resolve(ctx, str(args["dest"]))
        elif entry and Path(entry).parent != Path("."):
            target_dir = root / Path(entry).parent / "assets"
        else:
            target_dir = root / "assets"
        target_dir = target_dir.resolve()
        if target_dir != root and root not in target_dir.parents:
            return ToolResult.failure("destination escapes the project")
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / safe
        if target.exists():
            stem, suffix = target.stem, target.suffix
            n = 2
            while (target_dir / f"{stem}-{n}{suffix}").exists():
                n += 1
            target = target_dir / f"{stem}-{n}{suffix}"
        try:
            target.write_bytes(data)
        except OSError as exc:
            return ToolResult.failure(f"could not write image: {exc}")
        rel = target.relative_to(root).as_posix()
        entry_parent = (root / Path(entry).parent) if entry else root
        try:
            src = target.relative_to(entry_parent).as_posix()
        except ValueError:
            src = rel
        alt = str(args.get("alt") or Path(safe).stem.replace("-", " ").replace("_", " "))
        return ToolResult.success(
            f"installed image at {rel}; use src=\"{src}\"",
            path=rel, src=src, filename=target.name,
            bytes=len(data), alt=alt, mime=mime)


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
    return [ListDirTool(), ReadFileTool(), WriteFileTool(), EditFileTool(),
            RunCommandTool()]
