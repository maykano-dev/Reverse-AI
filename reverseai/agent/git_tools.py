"""Git tools - version control for the coding agent.

Local git operations on the project repository: status, diff, log, branch, and
commit. These run the real ``git`` binary in the project root (git itself is
trusted; the repository is the user's own), with the pager and interactive
prompts disabled and output size-capped.

Scope is deliberately local and reversible: there is no ``push`` and no remote
mutation here. Opening a pull request or reading CI needs network and auth,
which are operator-gated - do that through ``run_command`` with ``gh`` when the
operator has enabled coding network access.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .coding_tools import _project_root
from .tools import Permission, Tool, ToolResult

_MAX_OUTPUT = 20000
_GIT_ENV = {
    "GIT_PAGER": "cat", "PAGER": "cat", "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "HOME": os.environ.get("HOME", "/tmp"),
    # Keep any repo/user identity available for commits.
    "GIT_CONFIG_GLOBAL": os.environ.get("GIT_CONFIG_GLOBAL", ""),
}


def _run_git(root: Path, argv: list[str], timeout: float = 30.0):
    try:
        res = subprocess.run(
            ["git", *argv], cwd=str(root), env=_GIT_ENV,
            capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return None, "git is not installed", 127
    except subprocess.TimeoutExpired:
        return None, "git command timed out", 124
    out = (res.stdout or "") + (res.stderr or "")
    return res.returncode, out[:_MAX_OUTPUT], res.returncode


def _is_repo(root: Path) -> bool:
    code, _, _ = _run_git(root, ["rev-parse", "--is-inside-work-tree"])
    return code == 0


class _GitTool(Tool):
    permission = Permission.READ

    def _repo(self, ctx):
        root = _project_root(ctx)
        if not _is_repo(root):
            return None, ToolResult.failure(
                "not a git repository (run `git init` first, or set the project dir)")
        return root, None


class GitStatusTool(_GitTool):
    name = "git_status"
    description = ("Show the working-tree status: current branch, staged/unstaged "
                   "changes, and untracked files. Use it to see what you have changed.")
    parameters = {"type": "object", "properties": {}}

    def run(self, args, ctx) -> ToolResult:
        root, err = self._repo(ctx)
        if err:
            return err
        _, branch, _ = _run_git(root, ["branch", "--show-current"])
        code, out, _ = _run_git(root, ["status", "--short", "--branch"])
        if code != 0:
            return ToolResult.failure(out or "git status failed")
        return ToolResult.success(out or "(clean working tree)",
                                  branch=(branch or "").strip())


class GitDiffTool(_GitTool):
    name = "git_diff"
    description = (
        "Show changes as a unified diff. By default shows unstaged working-tree "
        "changes; set staged=true for the index, or give 'ref' to diff against a "
        "commit/branch (e.g. 'HEAD~1', 'main'). Limit to certain files with "
        "'paths'. Output is size-capped; pass 'stat'=true for a summary only."
    )
    parameters = {
        "type": "object",
        "properties": {
            "staged": {"type": "boolean", "default": False},
            "ref": {"type": "string", "description": "commit/branch to diff against"},
            "paths": {"type": "array", "items": {"type": "string"}},
            "stat": {"type": "boolean", "default": False},
        },
    }

    def run(self, args, ctx) -> ToolResult:
        root, err = self._repo(ctx)
        if err:
            return err
        argv = ["diff"]
        if args.get("staged"):
            argv.append("--cached")
        if args.get("stat"):
            argv.append("--stat")
        if args.get("ref"):
            argv.append(str(args["ref"]))
        paths = [str(p) for p in (args.get("paths") or [])]
        if paths:
            argv.append("--")
            argv.extend(paths)
        code, out, _ = _run_git(root, argv)
        if code != 0:
            return ToolResult.failure(out or "git diff failed")
        return ToolResult.success(out or "(no changes)")


class GitLogTool(_GitTool):
    name = "git_log"
    description = ("Show recent commit history (hash, author, date, subject). Set "
                   "'count' for how many, or 'paths' to limit to certain files.")
    parameters = {
        "type": "object",
        "properties": {
            "count": {"type": "integer", "default": 15, "minimum": 1, "maximum": 100},
            "paths": {"type": "array", "items": {"type": "string"}},
        },
    }

    def run(self, args, ctx) -> ToolResult:
        root, err = self._repo(ctx)
        if err:
            return err
        count = min(int(args.get("count", 15) or 15), 100)
        argv = ["log", f"-{count}", "--pretty=format:%h %an %ad %s", "--date=short"]
        paths = [str(p) for p in (args.get("paths") or [])]
        if paths:
            argv.append("--")
            argv.extend(paths)
        code, out, _ = _run_git(root, argv)
        if code != 0:
            return ToolResult.failure(out or "git log failed")
        return ToolResult.success(out or "(no commits yet)")


class GitBranchTool(_GitTool):
    name = "git_branch"
    description = (
        "List branches, or create/switch one. With no 'name', lists branches "
        "(current marked). With 'name' and create=true, creates and switches to "
        "it; with create=false, switches to an existing branch. Good practice is "
        "to work on a feature branch, not the default branch."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "branch to create or switch to"},
            "create": {"type": "boolean", "default": True},
        },
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        root, err = self._repo(ctx)
        if err:
            return err
        name = str(args.get("name") or "").strip()
        if not name:
            code, out, _ = _run_git(root, ["branch", "--all", "--verbose"])
            return (ToolResult.success(out or "(no branches)") if code == 0
                    else ToolResult.failure(out or "git branch failed"))
        if "/" in name and name.startswith(("-", "/")) or ".." in name or " " in name:
            return ToolResult.failure("invalid branch name")
        argv = ["switch", "-c", name] if args.get("create", True) else ["switch", name]
        code, out, _ = _run_git(root, argv)
        if code != 0:
            return ToolResult.failure(out or "could not change branch")
        return ToolResult.success(out or f"on branch {name}", branch=name)


class GitCommitTool(_GitTool):
    name = "git_commit"
    description = (
        "Record a commit. By default stages all changes (git add -A) then "
        "commits with 'message'; pass 'paths' to stage only those, or add=false "
        "to commit what is already staged. Writes local history only - it never "
        "pushes. Use a clear, conventional message. Commit when a change is "
        "complete and tests pass, not for every small edit."
    )
    parameters = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "add": {"type": "boolean", "default": True},
            "paths": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["message"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        root, err = self._repo(ctx)
        if err:
            return err
        message = str(args.get("message") or "").strip()
        if not message:
            return ToolResult.failure("commit message is required")
        paths = [str(p) for p in (args.get("paths") or [])]
        if paths:
            code, out, _ = _run_git(root, ["add", "--", *paths])
            if code != 0:
                return ToolResult.failure(out or "git add failed")
        elif args.get("add", True):
            code, out, _ = _run_git(root, ["add", "-A"])
            if code != 0:
                return ToolResult.failure(out or "git add failed")
        code, out, _ = _run_git(root, ["commit", "-m", message])
        if code != 0:
            return ToolResult.failure(out or "nothing to commit or commit failed")
        _, head, _ = _run_git(root, ["rev-parse", "--short", "HEAD"])
        return ToolResult.success(out, commit=(head or "").strip())


def git_tools() -> list[Tool]:
    return [GitStatusTool(), GitDiffTool(), GitLogTool(),
            GitBranchTool(), GitCommitTool()]
