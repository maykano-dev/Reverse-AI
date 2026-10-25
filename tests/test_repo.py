"""Source-repository map and its workspace boundary."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.builtins import AnalyzeRepositoryTool  # noqa: E402
from reverseai.agent.evidence import EvidenceLog  # noqa: E402
from reverseai.agent.tools import ToolContext  # noqa: E402
from reverseai.repo import build_repo_model  # noqa: E402


def make_repo(td: str) -> Path:
    root = Path(td) / "repo"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "src" / "main.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "# TODO: tighten this\n"
        "def main():\n    print('hi')\n")
    (root / "src" / "app.ts").write_text(
        "import {x} from './x';\nconst y = require('y');\n")
    (root / "tests" / "test_main.py").write_text("def test_x(): assert True\n")
    (root / "Makefile").write_text("all:\n\techo hi\n")
    return root


class RepoModelTests(unittest.TestCase):
    def test_structure_languages_imports_and_risks(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td)
            model = build_repo_model(root)
            s = model.summary()
            self.assertGreaterEqual(s["files"], 3)
            self.assertIn("Python", [x["name"] for x in model.languages])
            self.assertIn("TypeScript", [x["name"] for x in model.languages])
            self.assertIn("Make", model.build_systems)
            self.assertIn("src/main.py", model.imports)
            self.assertIn("os", model.imports["src/main.py"])
            self.assertTrue(model.tests)
            self.assertTrue(any(r["marker"] == "TODO"
                                for r in model.risk_markers))
            self.assertEqual(model.entry_points[0], "src/main.py")

    def test_non_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                build_repo_model(Path(td) / "missing")

    def test_tool_respects_workspace_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td)
            ctx = ToolContext(
                job_id="repo", workspace=str(root), target_path=None,
                evidence=EvidenceLog(), goal="map",
                extra={"project_dir": str(root)})
            result = AnalyzeRepositoryTool().run({}, ctx)
            self.assertTrue(result.ok, result.content)
            self.assertIn("repository", result.data)
            outside = AnalyzeRepositoryTool().run({"path": "/etc"}, ctx)
            self.assertFalse(outside.ok)
            self.assertIn("outside", outside.error or "")

    def test_tool_rejects_partial_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td)
            ctx = ToolContext(
                job_id="repo", workspace=str(root), target_path=None,
                evidence=EvidenceLog(), goal="map",
                extra={"project_dir": str(root)})
            result = AnalyzeRepositoryTool().run(
                {"path": str(root / "src")}, ctx)
            self.assertTrue(result.ok, result.content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
