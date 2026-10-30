"""Tests for the agentic-coding tools: search, outline, git, run_tests."""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from reverseai.agent.code_nav_tools import CodeOutlineTool, SearchCodeTool
from reverseai.agent.coding_tools import RunTestsTool, _detect_test_command, coding_tools
from reverseai.agent.git_tools import (
    GitBranchTool, GitCommitTool, GitDiffTool, GitLogTool, GitStatusTool,
)
from reverseai.agent.narrative import describe_tool
from reverseai.agent.tools import ToolContext


def _ctx(root):
    return ToolContext(job_id="t", workspace=str(root), extra={"project_dir": str(root)})


def _project(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, "utf-8")
    return d


class SearchCodeTests(unittest.TestCase):
    def test_literal_and_line_numbers(self):
        root = _project({"a.py": "x = 1\ndef hello():\n    return 1\n",
                         "b.py": "# nothing here\n"})
        r = SearchCodeTool().run({"query": "def hello"}, _ctx(root))
        self.assertTrue(r.ok)
        self.assertIn("a.py:2:", r.content)
        self.assertEqual(r.data["matches"], 1)

    def test_glob_narrows(self):
        root = _project({"a.py": "TODO fix\n", "a.txt": "TODO fix\n"})
        r = SearchCodeTool().run({"query": "TODO", "glob": "*.py"}, _ctx(root))
        self.assertEqual(r.data["files"], 1)

    def test_regex_and_context(self):
        root = _project({"a.py": "one\ntwo match_me three\nfour\n"})
        r = SearchCodeTool().run(
            {"query": r"match_\w+", "regex": True, "context": 1}, _ctx(root))
        self.assertTrue(r.ok)
        self.assertIn("one", r.content)   # context line before
        self.assertIn("four", r.content)  # context line after

    def test_no_match(self):
        root = _project({"a.py": "nothing\n"})
        r = SearchCodeTool().run({"query": "zzzzz"}, _ctx(root))
        self.assertTrue(r.ok)
        self.assertEqual(r.data["matches"], 0)

    def test_skips_binary_and_noise(self):
        root = _project({"keep.py": "needle\n",
                         "node_modules/x.py": "needle\n",
                         "img.png": "needle\n"})
        r = SearchCodeTool().run({"query": "needle"}, _ctx(root))
        self.assertEqual(r.data["files"], 1)

    def test_bad_regex_reports(self):
        root = _project({"a.py": "x\n"})
        r = SearchCodeTool().run({"query": "(unclosed", "regex": True}, _ctx(root))
        self.assertFalse(r.ok)


class CodeOutlineTests(unittest.TestCase):
    def test_python_symbols(self):
        root = _project({"m.py": "class Foo(Base):\n    def bar(self, x):\n"
                                 "        pass\n\ndef top():\n    return 1\n"})
        r = CodeOutlineTool().run({"path": "m.py"}, _ctx(root))
        self.assertTrue(r.ok)
        self.assertIn("class Foo", r.content)
        self.assertIn("def bar", r.content)
        self.assertIn("def top", r.content)

    def test_javascript_patterns(self):
        root = _project({"app.js": "export function go(){}\nclass Widget{}\n"})
        r = CodeOutlineTool().run({"path": "app.js"}, _ctx(root))
        self.assertTrue(r.ok)
        self.assertIn("go", r.content)
        self.assertIn("Widget", r.content)

    def test_directory_outline(self):
        root = _project({"a.py": "def one():\n    pass\n",
                         "sub/b.py": "def two():\n    pass\n"})
        r = CodeOutlineTool().run({"path": ".", "glob": "*.py"}, _ctx(root))
        self.assertEqual(r.data["files"], 2)


class GitToolTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        env = {"GIT_CONFIG_GLOBAL": "/dev/null", "HOME": str(self.root)}
        for argv in (["init", "-b", "main"],
                     ["config", "user.email", "t@example.com"],
                     ["config", "user.name", "Tester"]):
            subprocess.run(["git", *argv], cwd=self.root, env={**env, "PATH": "/usr/bin:/bin"},
                           capture_output=True, check=True)
        (self.root / "f.txt").write_text("hello\n")

    def test_status_and_commit_and_log(self):
        ctx = _ctx(self.root)
        st = GitStatusTool().run({}, ctx)
        self.assertTrue(st.ok)
        self.assertIn("f.txt", st.content)
        cm = GitCommitTool().run({"message": "init commit"}, ctx)
        self.assertTrue(cm.ok, cm.content)
        self.assertTrue(cm.data.get("commit"))
        lg = GitLogTool().run({"count": 5}, ctx)
        self.assertIn("init commit", lg.content)

    def test_diff_shows_change(self):
        ctx = _ctx(self.root)
        GitCommitTool().run({"message": "base"}, ctx)
        (self.root / "f.txt").write_text("hello world\n")
        df = GitDiffTool().run({}, ctx)
        self.assertTrue(df.ok)
        self.assertIn("world", df.content)

    def test_branch_create_and_list(self):
        ctx = _ctx(self.root)
        GitCommitTool().run({"message": "base"}, ctx)
        br = GitBranchTool().run({"name": "feature/x", "create": True}, ctx)
        self.assertTrue(br.ok, br.content)
        self.assertEqual(br.data.get("branch"), "feature/x")
        lst = GitBranchTool().run({}, ctx)
        self.assertIn("feature/x", lst.content)

    def test_not_a_repo(self):
        plain = Path(tempfile.mkdtemp())
        r = GitStatusTool().run({}, _ctx(plain))
        self.assertFalse(r.ok)
        self.assertIn("not a git repository", r.content)


class RunTestsDetectionTests(unittest.TestCase):
    def test_detect_pytest(self):
        root = _project({"pyproject.toml": "[tool.pytest.ini_options]\n"})
        argv, kind = _detect_test_command(root)
        self.assertEqual(kind, "pytest")

    def test_detect_unittest(self):
        root = _project({"tests/test_x.py": "def test(): pass\n"})
        argv, kind = _detect_test_command(root)
        self.assertEqual(kind, "unittest")

    def test_detect_npm(self):
        root = _project({"package.json": '{"scripts": {"test": "jest"}}'})
        argv, kind = _detect_test_command(root)
        self.assertEqual(kind, "npm")

    def test_detect_none(self):
        root = _project({"readme.md": "hi\n"})
        argv, kind = _detect_test_command(root)
        self.assertIsNone(argv)


class HonestyTests(unittest.TestCase):
    """Every coding tool must have narration and a UI label (no raw tool names)."""

    def test_narration_and_labels(self):
        app = (Path(__file__).resolve().parent.parent
               / "reverseai/server/static/app.js").read_text("utf-8")
        for tool in coding_tools():
            d = describe_tool(tool.name, {})
            self.assertTrue(d["title"].strip(), f"{tool.name} has no narration title")
            self.assertTrue(re.search(re.escape(tool.name) + r"\s*:", app),
                            f"{tool.name} has no UI label in app.js")


if __name__ == "__main__":
    unittest.main()
