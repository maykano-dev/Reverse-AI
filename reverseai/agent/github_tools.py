"""GitHub tools - open a pull request and read CI, via the `gh` CLI.

These finish the coding loop the way Claude Code does: after committing on a
branch, open a PR and read its checks. Unlike the local git tools, these are
OUTWARD-FACING and use the network, so they are gated:

- The operator must opt in with ``REVERSEAI_ALLOW_GITHUB=1``. Without it the
  tools refuse and say so - no silent network or publishing.
- They shell out to the user's authenticated ``gh`` (argv, no shell string), so
  they act as the user on the user's own repo. Opening a PR also pushes the
  current branch to its remote; that is stated plainly.

Everything ``gh`` returns is data, never instructions.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .coding_tools import _project_root
from .tools import Permission, Tool, ToolResult

_MAX_OUTPUT = 16000
_GH_ENV = {
    "GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1", "CLICOLOR": "0",
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "HOME": os.environ.get("HOME", "/tmp"),
}


def _github_allowed() -> tuple[bool, str]:
    if os.environ.get("REVERSEAI_ALLOW_GITHUB") != "1":
        return False, ("GitHub access is off. It reaches the network and pushes "
                       "to a remote, so the operator must enable it with "
                       "REVERSEAI_ALLOW_GITHUB=1 and have `gh` authenticated.")
    return True, ""


def _run_gh(root: Path, argv: list[str], timeout: float = 60.0):
    env = {**_GH_ENV}
    for k in ("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR", "XDG_CONFIG_HOME",
              "SSH_AUTH_SOCK"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    try:
        res = subprocess.run(["gh", *argv], cwd=str(root), env=env,
                             capture_output=True, text=True, timeout=timeout,
                             check=False)
    except FileNotFoundError:
        return 127, "the GitHub CLI `gh` is not installed"
    except subprocess.TimeoutExpired:
        return 124, "gh command timed out"
    out = ((res.stdout or "") + (res.stderr or "")).strip()
    return res.returncode, out[:_MAX_OUTPUT]


class _GhTool(Tool):
    def _guard(self, ctx):
        ok, msg = _github_allowed()
        if not ok:
            return None, ToolResult.failure(msg)
        root = _project_root(ctx)
        code, out = _run_gh(root, ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
        if code == 127:
            return None, ToolResult.failure(out)
        if code != 0:
            return None, ToolResult.failure(
                "not an authenticated GitHub repo here (`gh auth login` and a "
                "GitHub remote are required): " + out)
        return root, None


class OpenPullRequestTool(_GhTool):
    name = "open_pr"
    description = (
        "Open a GitHub pull request for the current branch. This is outward "
        "facing: it pushes the current branch to its remote and creates a PR, so "
        "commit your work on a feature branch first (git_branch, git_commit). "
        "Give a clear 'title' and a 'body' (markdown). Optional 'base' (target "
        "branch, defaults to the repo default), and draft=true for a draft PR. "
        "Returns the PR URL. Requires the operator to have enabled GitHub access."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string", "default": ""},
            "base": {"type": "string", "description": "target branch (default: repo default)"},
            "draft": {"type": "boolean", "default": False},
        },
        "required": ["title"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        root, err = self._guard(ctx)
        if err:
            return err
        title = str(args.get("title") or "").strip()
        if not title:
            return ToolResult.failure("a PR title is required")
        argv = ["pr", "create", "--title", title, "--body", str(args.get("body") or "")]
        if args.get("base"):
            argv += ["--base", str(args["base"])]
        if args.get("draft"):
            argv.append("--draft")
        code, out = _run_gh(root, argv, timeout=120)
        if code != 0:
            return ToolResult.failure(out or "could not open the pull request")
        url = next((ln for ln in out.splitlines() if ln.startswith("http")), out)
        return ToolResult.success(f"opened pull request: {url}", url=url)


class PullRequestStatusTool(_GhTool):
    name = "pr_status"
    description = (
        "Read the status of a GitHub pull request and its CI checks - the way to "
        "see whether a PR is passing before merging. With no argument it reports "
        "the PR for the current branch; pass 'pr' as a number, URL, or branch. "
        "Returns title, state, mergeability, and each check's result. Read-only, "
        "but it uses the network, so GitHub access must be enabled."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pr": {"type": "string", "description": "PR number, URL, or branch (default: current branch)"},
        },
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        root, err = self._guard(ctx)
        if err:
            return err
        pr = str(args.get("pr") or "").strip()
        view = ["pr", "view"] + ([pr] if pr else []) + [
            "--json", "title,state,isDraft,mergeable,url,headRefName",
            "--template",
            ("{{.title}} [{{.state}}{{if .isDraft}}, draft{{end}}]\n"
             "branch {{.headRefName}}  mergeable: {{.mergeable}}\n{{.url}}")]
        code, out = _run_gh(root, view)
        if code != 0:
            return ToolResult.failure(out or "no pull request found for this branch")
        checks_argv = ["pr", "checks"] + ([pr] if pr else [])
        ccode, cout = _run_gh(root, checks_argv)
        # `gh pr checks` exits non-zero when checks fail or are pending; that is
        # information, not a tool error.
        checks = cout or ("no checks reported" if ccode == 0 else cout)
        passing = ccode == 0
        return ToolResult.success(out + "\n\n--- checks ---\n" + checks,
                                  checks_passing=passing)


def github_tools() -> list[Tool]:
    return [OpenPullRequestTool(), PullRequestStatusTool()]
