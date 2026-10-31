"""Tests for the GitHub PR / CI tools (gated, gh-backed)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reverseai.agent import github_tools as gh
from reverseai.agent.tools import ToolContext


def _ctx():
    d = tempfile.mkdtemp()
    return ToolContext(job_id="t", workspace=d, extra={"project_dir": d})


class GateTests(unittest.TestCase):
    def test_refuses_without_opt_in(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("REVERSEAI_ALLOW_GITHUB", None)
            r = gh.OpenPullRequestTool().run({"title": "x"}, _ctx())
            self.assertFalse(r.ok)
            self.assertIn("REVERSEAI_ALLOW_GITHUB", r.content)

    def test_gh_missing_reported(self):
        with mock.patch.dict(os.environ, {"REVERSEAI_ALLOW_GITHUB": "1"}):
            with mock.patch.object(gh, "_run_gh", return_value=(127, "the GitHub CLI `gh` is not installed")):
                r = gh.PullRequestStatusTool().run({}, _ctx())
                self.assertFalse(r.ok)
                self.assertIn("gh", r.content)

    def test_not_a_repo_reported(self):
        with mock.patch.dict(os.environ, {"REVERSEAI_ALLOW_GITHUB": "1"}):
            with mock.patch.object(gh, "_run_gh", return_value=(1, "no git remotes found")):
                r = gh.OpenPullRequestTool().run({"title": "x"}, _ctx())
                self.assertFalse(r.ok)
                self.assertIn("authenticated GitHub repo", r.content)


class OpenPRTests(unittest.TestCase):
    def test_builds_argv_and_returns_url(self):
        calls = []

        def fake(root, argv, timeout=60.0):
            calls.append(argv)
            if argv[:2] == ["repo", "view"]:
                return 0, "owner/repo"
            if argv[:2] == ["pr", "create"]:
                return 0, "https://github.com/owner/repo/pull/7"
            return 1, "unexpected"

        with mock.patch.dict(os.environ, {"REVERSEAI_ALLOW_GITHUB": "1"}):
            with mock.patch.object(gh, "_run_gh", side_effect=fake):
                r = gh.OpenPullRequestTool().run(
                    {"title": "Add feature", "body": "does X", "base": "main", "draft": True}, _ctx())
        self.assertTrue(r.ok, r.content)
        self.assertEqual(r.data["url"], "https://github.com/owner/repo/pull/7")
        create = [c for c in calls if c[:2] == ["pr", "create"]][0]
        self.assertIn("--title", create)
        self.assertIn("Add feature", create)
        self.assertIn("--base", create)
        self.assertIn("main", create)
        self.assertIn("--draft", create)

    def test_requires_title(self):
        with mock.patch.dict(os.environ, {"REVERSEAI_ALLOW_GITHUB": "1"}):
            with mock.patch.object(gh, "_run_gh", return_value=(0, "owner/repo")):
                r = gh.OpenPullRequestTool().run({"title": "  "}, _ctx())
                self.assertFalse(r.ok)


class PRStatusTests(unittest.TestCase):
    def test_reports_checks(self):
        def fake(root, argv, timeout=60.0):
            if argv[:2] == ["repo", "view"]:
                return 0, "owner/repo"
            if argv[:2] == ["pr", "view"]:
                return 0, "Add feature [OPEN]\nbranch feat  mergeable: MERGEABLE\nhttps://x/pull/7"
            if argv[:2] == ["pr", "checks"]:
                return 0, "build  pass  1m"
            return 1, "?"

        with mock.patch.dict(os.environ, {"REVERSEAI_ALLOW_GITHUB": "1"}):
            with mock.patch.object(gh, "_run_gh", side_effect=fake):
                r = gh.PullRequestStatusTool().run({}, _ctx())
        self.assertTrue(r.ok, r.content)
        self.assertTrue(r.data["checks_passing"])
        self.assertIn("Add feature", r.content)
        self.assertIn("build", r.content)

    def test_failing_checks_not_an_error(self):
        def fake(root, argv, timeout=60.0):
            if argv[:2] == ["repo", "view"]:
                return 0, "owner/repo"
            if argv[:2] == ["pr", "view"]:
                return 0, "PR [OPEN]"
            if argv[:2] == ["pr", "checks"]:
                return 1, "build  fail"
            return 1, "?"

        with mock.patch.dict(os.environ, {"REVERSEAI_ALLOW_GITHUB": "1"}):
            with mock.patch.object(gh, "_run_gh", side_effect=fake):
                r = gh.PullRequestStatusTool().run({}, _ctx())
        self.assertTrue(r.ok)                      # reported, not a tool error
        self.assertFalse(r.data["checks_passing"])
        self.assertIn("fail", r.content)


class RegistrationTests(unittest.TestCase):
    def test_in_coding_tools_with_narration_and_label(self):
        from reverseai.agent.coding_tools import coding_tools
        from reverseai.agent.narrative import describe_tool
        names = {t.name for t in coding_tools()}
        self.assertIn("open_pr", names)
        self.assertIn("pr_status", names)
        app = (Path(__file__).resolve().parent.parent
               / "reverseai/server/static/app.js").read_text("utf-8")
        for n in ("open_pr", "pr_status"):
            self.assertTrue(describe_tool(n, {})["title"].strip())
            self.assertIn(n + ":", app)


if __name__ == "__main__":
    unittest.main()
