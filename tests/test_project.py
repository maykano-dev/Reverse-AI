"""Tests for the persistent project workbook and project tools."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reverseai import project
from reverseai.agent.project_tools import (
    ReadProjectPlanTool, SetProjectFolderTool, UpdateProjectPlanTool,
)
from reverseai.agent.tools import ToolContext


def _ctx(root):
    return ToolContext(job_id="t", workspace=str(root), extra={"project_dir": str(root)})


class WorkbookTests(unittest.TestCase):
    def test_update_and_load_roundtrip(self):
        d = tempfile.mkdtemp()
        project.update_plan(d, goal="Build a parser", add_steps=["lex", "parse"])
        plan = project.load_plan(d)
        self.assertEqual(plan["goal"], "Build a parser")
        self.assertEqual([s["text"] for s in plan["steps"]], ["lex", "parse"])
        self.assertTrue(project.has_plan(d))
        # writes a human-readable PROJECT.md too
        self.assertTrue((Path(d) / ".reverseai" / "PROJECT.md").is_file())

    def test_complete_step_by_text_and_index(self):
        d = tempfile.mkdtemp()
        project.update_plan(d, add_steps=["alpha", "beta", "gamma"])
        project.update_plan(d, complete=["alpha", 2])
        steps = {s["text"]: s["done"] for s in project.load_plan(d)["steps"]}
        self.assertTrue(steps["alpha"])
        self.assertFalse(steps["beta"])
        self.assertTrue(steps["gamma"])

    def test_notes_accumulate_with_timestamp(self):
        d = tempfile.mkdtemp()
        project.update_plan(d, notes="chose SQLite")
        project.update_plan(d, notes=["added index", "fixed race"])
        notes = project.load_plan(d)["notes"]
        self.assertEqual(len(notes), 3)
        self.assertTrue(any("SQLite" in n for n in notes))

    def test_state_block_present_and_empty(self):
        d = tempfile.mkdtemp()
        self.assertEqual(project.project_state_block(d), "")
        project.update_plan(d, goal="Ship it", add_steps=["do thing"])
        block = project.project_state_block(d)
        self.assertIn("Ship it", block)
        self.assertIn("do thing", block)
        self.assertIn("Folder:", block)
        self.assertEqual(project.project_state_block(None), "")

    def test_scan_empty_vs_existing(self):
        empty = tempfile.mkdtemp()
        self.assertTrue(project.scan_folder(empty)["empty"])
        full = tempfile.mkdtemp()
        (Path(full) / "main.py").write_text("x=1\n")
        info = project.scan_folder(full)
        self.assertFalse(info["empty"])
        self.assertIn("main.py", info["entries"])
        # .git / .reverseai do not count as user content
        (Path(empty) / ".git").mkdir()
        self.assertTrue(project.scan_folder(empty)["empty"])


class ProjectToolTests(unittest.TestCase):
    def test_set_folder_reports_empty(self):
        d = tempfile.mkdtemp()
        ctx = _ctx(d)
        r = SetProjectFolderTool().run({"path": d}, ctx)
        self.assertTrue(r.ok)
        self.assertIn("empty", r.content)
        self.assertEqual(ctx.extra["project_dir"], str(Path(d).resolve()))

    def test_set_folder_reports_existing(self):
        d = tempfile.mkdtemp()
        (Path(d) / "app.py").write_text("print(1)\n")
        r = SetProjectFolderTool().run({"path": d}, _ctx(d))
        self.assertTrue(r.ok)
        self.assertIn("existing project", r.content)
        self.assertIn("app.py", r.content)

    def test_set_folder_missing_without_create(self):
        missing = str(Path(tempfile.mkdtemp()) / "nope")
        r = SetProjectFolderTool().run({"path": missing}, _ctx("."))
        self.assertFalse(r.ok)

    def test_set_folder_create(self):
        missing = str(Path(tempfile.mkdtemp()) / "fresh")
        r = SetProjectFolderTool().run({"path": missing, "create": True}, _ctx("."))
        self.assertTrue(r.ok)
        self.assertTrue(Path(missing).is_dir())

    def test_update_and_read_plan_tools(self):
        d = tempfile.mkdtemp()
        ctx = _ctx(d)
        u = UpdateProjectPlanTool().run(
            {"goal": "Make a CLI", "add_steps": ["args", "run"], "note": "use argparse"}, ctx)
        self.assertTrue(u.ok)
        self.assertEqual(u.data["steps_total"], 2)
        UpdateProjectPlanTool().run({"complete": ["args"]}, ctx)
        self.assertEqual(UpdateProjectPlanTool().run({}, ctx).data["steps_done"], 1)
        r = ReadProjectPlanTool().run({}, ctx)
        self.assertTrue(r.data["exists"])
        self.assertIn("Make a CLI", r.content)

    def test_read_plan_none(self):
        r = ReadProjectPlanTool().run({}, _ctx(tempfile.mkdtemp()))
        self.assertFalse(r.data["exists"])


class RegistrationTests(unittest.TestCase):
    def test_registered_with_narration_and_labels(self):
        from reverseai.agent.coding_tools import coding_tools
        from reverseai.agent.narrative import describe_tool
        names = {t.name for t in coding_tools()}
        app = (Path(__file__).resolve().parent.parent
               / "reverseai/server/static/app.js").read_text("utf-8")
        for n in ("set_project_folder", "update_project_plan", "read_project_plan"):
            self.assertIn(n, names)
            self.assertTrue(describe_tool(n, {})["title"].strip())
            self.assertIn(n + ":", app)


if __name__ == "__main__":
    unittest.main()
