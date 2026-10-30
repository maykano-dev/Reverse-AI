"""Codebase navigation: search_code and code_outline.

A coding agent should not read whole files to find things. These two read-only
tools let it navigate a large project the way a developer does:

- ``search_code`` is a ripgrep-style content search (literal or regex) over the
  project, with file globbing and optional surrounding context. It skips the
  usual noise (``.git``, ``node_modules``, ``__pycache__``, build output) and
  binary files, and caps its own output so a broad query stays readable.
- ``code_outline`` is a symbol map: the classes/functions defined in a file or
  across a directory, with line numbers. Python is parsed with ``ast`` (exact);
  other languages use conservative definition patterns.

Both are pure Python (no ripgrep/ctags dependency) and contained to the project
root through ``safe_join``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..security.validate import ValidationError
from .coding_tools import _project_root, _resolve
from .tools import Permission, Tool, ToolResult

# Directories never worth searching, and extensions that are not source text.
_SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".mypy_cache",
              ".pytest_cache", ".ruff_cache", ".venv", "venv", "env", "dist",
              "build", ".next", ".nuxt", "target", ".idea", ".vscode", ".cache",
              "coverage", ".tox", "vendor", ".studio"}
_BINARY_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".ico", ".bmp",
                ".pdf", ".zip", ".gz", ".tar", ".xz", ".7z", ".rar", ".jar",
                ".pptx", ".docx", ".xlsx", ".exe", ".dll", ".so", ".dylib", ".o",
                ".a", ".bin", ".class", ".pyc", ".wasm", ".mp3", ".mp4", ".mov",
                ".wav", ".ogg", ".woff", ".woff2", ".ttf", ".otf", ".eot"}
_MAX_FILE_BYTES = 2 * 1024 * 1024
_MAX_MATCHES = 400
_MAX_OUTPUT = 24000


def _iter_files(base: Path, glob: str | None):
    """Yield candidate source files under ``base``, skipping noise and binaries."""
    if base.is_file():
        yield base
        return
    pat = glob.strip() if isinstance(glob, str) and glob.strip() else None
    for p in sorted(base.rglob("*")):
        if p.is_dir():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in _BINARY_EXTS:
            continue
        if pat and not p.match(pat) and not p.name == pat:
            continue
        try:
            if p.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield p


class SearchCodeTool(Tool):
    name = "search_code"
    description = (
        "Search the project's source for text - the fast way to find where "
        "something is defined or used, instead of reading whole files. 'query' "
        "is a literal string by default, or a regular expression when "
        "regex=true. Narrow with 'glob' (e.g. '*.py', '*.ts'), 'path' (a "
        "subdirectory), and 'ignore_case'. Returns matching 'path:line: text' "
        "lines; set 'context' to also show N lines around each match. It skips "
        ".git, node_modules, build output, and binary files, and caps its "
        "output, so start broad then narrow. Use this before edit_file to "
        "locate call sites and definitions across a large codebase."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "text or regex to find"},
            "regex": {"type": "boolean", "default": False},
            "path": {"type": "string", "default": ".",
                     "description": "file or subdirectory to search"},
            "glob": {"type": "string", "description": "file filter, e.g. '*.py'"},
            "ignore_case": {"type": "boolean", "default": False},
            "context": {"type": "integer", "default": 0, "minimum": 0, "maximum": 6,
                        "description": "lines of context around each match"},
            "max_results": {"type": "integer", "default": 200, "minimum": 1,
                            "maximum": _MAX_MATCHES},
        },
        "required": ["query"],
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        query = str(args.get("query") or "")
        if not query:
            return ToolResult.failure("query is required")
        flags = re.IGNORECASE if args.get("ignore_case") else 0
        try:
            if args.get("regex"):
                rx = re.compile(query, flags)
            else:
                rx = re.compile(re.escape(query), flags)
        except re.error as exc:
            return ToolResult.failure(f"invalid regex: {exc}")
        try:
            base = _resolve(ctx, args.get("path", "."))
        except ValidationError as exc:
            return ToolResult.failure(str(exc))
        if not base.exists():
            return ToolResult.failure(f"no such path: {args.get('path', '.')}")

        root = _project_root(ctx).resolve()
        base = base.resolve()
        ctxn = min(int(args.get("context", 0) or 0), 6)
        cap = min(int(args.get("max_results", 200) or 200), _MAX_MATCHES)
        out: list[str] = []
        total = 0
        files_hit = 0
        size = 0
        truncated = False
        for fp in _iter_files(base, args.get("glob")):
            try:
                lines = fp.read_text("utf-8", "replace").splitlines()
            except OSError:
                continue
            rel = fp.relative_to(root).as_posix()
            hit_in_file = False
            for i, line in enumerate(lines):
                if not rx.search(line):
                    continue
                if not hit_in_file:
                    files_hit += 1
                    hit_in_file = True
                total += 1
                if ctxn:
                    lo, hi = max(0, i - ctxn), min(len(lines), i + ctxn + 1)
                    block = [f"{rel}:{j+1}:{'>' if j == i else ' '} {lines[j][:300]}"
                             for j in range(lo, hi)]
                    chunk = "\n".join(block) + "\n--"
                else:
                    chunk = f"{rel}:{i+1}: {line[:300]}"
                out.append(chunk)
                size += len(chunk)
                if total >= cap or size >= _MAX_OUTPUT:
                    truncated = True
                    break
            if truncated:
                break

        if not out:
            return ToolResult.success(f"no matches for {query!r}", matches=0)
        header = f"{total} match(es) in {files_hit} file(s)"
        if truncated:
            header += " (truncated - narrow with glob/path)"
        return ToolResult.success(header + "\n" + "\n".join(out),
                                  matches=total, files=files_hit, truncated=truncated)


# --- symbol extraction ------------------------------------------------------
def _py_symbols(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out: list[str] = []

    def visit(node, depth):
        for child in getattr(node, "body", []):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = ", ".join(p.arg for p in child.args.args)
                kind = "async def" if isinstance(child, ast.AsyncFunctionDef) else "def"
                out.append(f"{child.lineno}\t{'  ' * depth}{kind} {child.name}({a})")
                visit(child, depth + 1)
            elif isinstance(child, ast.ClassDef):
                bases = ", ".join(ast.unparse(b) for b in child.bases) if child.bases else ""
                out.append(f"{child.lineno}\t{'  ' * depth}class {child.name}"
                           f"{('(' + bases + ')') if bases else ''}")
                visit(child, depth + 1)

    visit(tree, 0)
    return out


# Conservative definition patterns for common non-Python languages.
_LANG_PATTERNS = {
    (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"): [
        re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)"),
        re.compile(r"^\s*(?:export\s+)?class\s+(\w+)"),
        re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"),
    ],
    (".go",): [re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)"),
               re.compile(r"^\s*type\s+(\w+)\s+(?:struct|interface)")],
    (".rs",): [re.compile(r"^\s*(?:pub\s+)?fn\s+(\w+)"),
               re.compile(r"^\s*(?:pub\s+)?(?:struct|enum|trait)\s+(\w+)")],
    (".java", ".kt", ".cs"): [
        re.compile(r"^\s*(?:public|private|protected).*\bclass\s+(\w+)"),
        re.compile(r"^\s*(?:public|private|protected|static|final|\s)+[\w<>\[\]]+\s+(\w+)\s*\("),
    ],
    (".c", ".h", ".cpp", ".cc", ".hpp", ".cxx"): [
        re.compile(r"^\s*(?:[\w:<>\*&]+\s+)+(\w+)\s*\([^;]*\)\s*\{?\s*$"),
        re.compile(r"^\s*(?:class|struct)\s+(\w+)"),
    ],
    (".rb",): [re.compile(r"^\s*def\s+([\w\.?!]+)"), re.compile(r"^\s*class\s+(\w+)")],
    (".php",): [re.compile(r"^\s*(?:public|private|protected|static|\s)*function\s+(\w+)"),
                re.compile(r"^\s*class\s+(\w+)")],
}


def _regex_symbols(text: str, suffix: str) -> list[str]:
    pats = None
    for exts, plist in _LANG_PATTERNS.items():
        if suffix in exts:
            pats = plist
            break
    if not pats:
        return []
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        for pat in pats:
            m = pat.match(line)
            if m:
                out.append(f"{i}\t{line.strip()[:120]}")
                break
    return out


class CodeOutlineTool(Tool):
    name = "code_outline"
    description = (
        "Map the symbols (classes, functions, methods) defined in a file or "
        "across a directory, with line numbers - a table of contents for code "
        "so you can jump to a definition instead of reading the whole file. "
        "Python is parsed exactly; JS/TS, Go, Rust, Java/Kotlin/C#, C/C++, Ruby "
        "and PHP use definition patterns. Give 'path' as a file or a directory; "
        "filter a directory with 'glob'. Pair it with search_code to navigate a "
        "codebase quickly."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": "."},
            "glob": {"type": "string", "description": "file filter for a directory, e.g. '*.py'"},
            "max_files": {"type": "integer", "default": 60, "minimum": 1, "maximum": 300},
        },
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        try:
            base = _resolve(ctx, args.get("path", "."))
        except ValidationError as exc:
            return ToolResult.failure(str(exc))
        if not base.exists():
            return ToolResult.failure(f"no such path: {args.get('path', '.')}")
        root = _project_root(ctx).resolve()
        base = base.resolve()
        cap = min(int(args.get("max_files", 60) or 60), 300)
        sections: list[str] = []
        nfiles = nsyms = 0
        size = 0
        for fp in _iter_files(base, args.get("glob")):
            if nfiles >= cap:
                sections.append("... (more files; narrow with path/glob)")
                break
            try:
                text = fp.read_text("utf-8", "replace")
            except OSError:
                continue
            suffix = fp.suffix.lower()
            syms = _py_symbols(text) if suffix == ".py" else _regex_symbols(text, suffix)
            if not syms:
                continue
            rel = fp.relative_to(root).as_posix()
            nfiles += 1
            nsyms += len(syms)
            block = f"# {rel}\n" + "\n".join(syms[:200])
            sections.append(block)
            size += len(block)
            if size >= _MAX_OUTPUT:
                sections.append("... (output truncated; narrow with path/glob)")
                break
        if not sections:
            return ToolResult.success("no symbols found (unsupported language or empty)",
                                      symbols=0, files=0)
        return ToolResult.success("\n\n".join(sections), symbols=nsyms, files=nfiles)


def code_nav_tools() -> list[Tool]:
    return [SearchCodeTool(), CodeOutlineTool()]
