"""Coding-agent tool tests, including a write-and-run loop in the sandbox.

Run: python3 -m unittest tests.test_coding -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent import (  # noqa: E402
    Agent, Permission, ToolContext, ToolMediator, ToolRegistry,
)
from reverseai.agent.coding_tools import InstallMediaTool, coding_tools  # noqa: E402
from reverseai.agent.providers.mock import MockProvider, call, say  # noqa: E402
from reverseai.sandbox import SandboxPolicy  # noqa: E402


def tool(name):
    for t in coding_tools():
        if t.name == name:
            return t
    raise KeyError(name)


class FileToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = ToolContext(job_id="t", workspace=self.tmp.name,
                               extra={"project_dir": self.tmp.name})

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_read_roundtrip(self):
        r = tool("write_file").run({"path": "a/b.txt", "content": "hello\nworld"}, self.ctx)
        self.assertTrue(r.ok, r.content)
        r2 = tool("read_file").run({"path": "a/b.txt"}, self.ctx)
        self.assertIn("hello", r2.content)

    def test_append_builds_a_file_in_chunks(self):
        tool("write_file").run({"path": "big.txt", "content": "one\n"}, self.ctx)
        r = tool("write_file").run(
            {"path": "big.txt", "content": "two\n", "append": True}, self.ctx)
        self.assertTrue(r.ok, r.content)
        self.assertEqual(Path(self.tmp.name, "big.txt").read_text(),
                         "one\ntwo\n")

    def test_edit_unique(self):
        tool("write_file").run({"path": "f.py", "content": "x = 1\ny = 1\n"}, self.ctx)
        r = tool("edit_file").run({"path": "f.py", "old": "x = 1", "new": "x = 2"}, self.ctx)
        self.assertTrue(r.ok)
        self.assertIn("x = 2", tool("read_file").run({"path": "f.py"}, self.ctx).content)

    def test_edit_ambiguous_refused(self):
        tool("write_file").run({"path": "f.py", "content": "a\na\n"}, self.ctx)
        r = tool("edit_file").run({"path": "f.py", "old": "a", "new": "b"}, self.ctx)
        self.assertFalse(r.ok)

    def test_path_traversal_refused(self):
        r = tool("write_file").run({"path": "../escape.txt", "content": "x"}, self.ctx)
        self.assertFalse(r.ok)
        r2 = tool("read_file").run({"path": "../../etc/passwd"}, self.ctx)
        self.assertFalse(r2.ok)

    def test_list_dir(self):
        tool("write_file").run({"path": "one.txt", "content": "1"}, self.ctx)
        tool("write_file").run({"path": "sub/two.txt", "content": "2"}, self.ctx)
        r = tool("list_dir").run({"path": "."}, self.ctx)
        self.assertIn("one.txt", r.content)
        self.assertIn("sub", r.content)


PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


class MediaToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ctx = ToolContext(job_id="t", workspace=self.tmp.name,
                               extra={"project_dir": self.tmp.name})

    def tearDown(self):
        self.tmp.cleanup()

    def test_installs_an_uploaded_image_into_site_assets(self):
        site = self.root / "site"
        site.mkdir()
        (site / "index.html").write_text("<h1>x</h1>")
        (self.root / "photo.png").write_bytes(PNG)
        r = InstallMediaTool().run({"source": "photo.png"}, self.ctx)
        self.assertTrue(r.ok, r.content)
        self.assertEqual(r.data["path"], "site/assets/photo.png")
        self.assertEqual(r.data["src"], "assets/photo.png")
        self.assertTrue((site / "assets" / "photo.png").is_file())

    def test_accepts_an_image_in_the_store_upload_root(self):
        uploads = self.root / "uploads" / "u1"
        uploads.mkdir(parents=True)
        source = uploads / "shot.png"
        source.write_bytes(PNG)
        self.ctx.extra["upload_root"] = str(self.root / "uploads")
        r = InstallMediaTool().run({"source": str(source), "dest": "assets"}, self.ctx)
        self.assertTrue(r.ok, r.content)
        self.assertTrue((self.root / "assets" / "shot.png").is_file())

    def test_refuses_a_disguised_text_file(self):
        (self.root / "fake.png").write_text("not an image")
        r = InstallMediaTool().run({"source": "fake.png"}, self.ctx)
        self.assertFalse(r.ok)
        self.assertIn("does not look like", r.content)

    def test_refuses_a_path_outside_the_project_and_uploads(self):
        outside = Path(tempfile.mkdtemp()) / "secret.png"
        outside.write_bytes(PNG)
        try:
            r = InstallMediaTool().run({"source": str(outside)}, self.ctx)
            self.assertFalse(r.ok)
            self.assertIn("uploaded file or inside the project", r.content)
        finally:
            outside.unlink(missing_ok=True)
            outside.parent.rmdir()

    def test_fetches_a_public_image_url(self):
        from unittest.mock import patch

        with patch("reverseai.agent.coding_tools.safe_fetch",
                   return_value=(PNG, "image/png", "https://example.com/photo.png")):
            r = InstallMediaTool().run(
                {"source": "https://example.com/photo.png"}, self.ctx)
        self.assertTrue(r.ok, r.content)
        self.assertTrue((self.root / "assets" / "photo.png").is_file())


class PreviewTests(unittest.TestCase):
    def test_generated_site_is_detected_as_a_preview(self):
        with tempfile.TemporaryDirectory() as td:
            agent = Agent(MockProvider([]), max_permission=Permission.WRITE)
            conv = agent.open(project_dir=td, workspace=td)
            site = Path(td) / "site"
            site.mkdir()
            (site / "index.html").write_text("<h1>preview me</h1>")
            rel, _fresh = conv._preview_entry()
            self.assertEqual(rel, "site/index.html")

    def test_write_then_finish_records_the_preview(self):
        with tempfile.TemporaryDirectory() as td:
            script = [
                call("write_file", {"path": "site/index.html",
                                    "content": "<h1>built</h1>"}),
                say("Built it."),
            ]
            agent = Agent(MockProvider(script), max_permission=Permission.WRITE)
            events = []
            job = agent.run("build a page", project_dir=td, workspace=td,
                            on_event=events.append)
            self.assertEqual(job.preview, "site/index.html")
            self.assertTrue(any(e.get("type") == "preview_changed"
                                for e in events))


class OutputBudgetTests(unittest.TestCase):
    def test_output_budget_is_large_enough_and_configurable(self):
        agent = Agent(MockProvider([]), max_permission=Permission.READ)
        self.assertGreaterEqual(agent.max_tokens, 8192)
        explicit = Agent(MockProvider([]), max_permission=Permission.READ,
                         max_tokens=1234)
        self.assertEqual(explicit.max_tokens, 1234)

    def test_truncated_arguments_get_an_actionable_error(self):
        with tempfile.TemporaryDirectory() as td:
            reg = ToolRegistry()
            for t in coding_tools():
                reg.register(t)
            med = ToolMediator(reg, max_permission=Permission.WRITE)
            ctx = ToolContext(job_id="t", workspace=td,
                              extra={"project_dir": td})
            res = med.dispatch("write_file", {"__raw__": '{"path": "x"'}, ctx)
            self.assertFalse(res.ok)
            self.assertIn("not valid JSON", res.content)
            self.assertIn("skeleton", res.content)
            self.assertIn("truncated response", med.audit[-1].note)


class RunCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ctx = ToolContext(job_id="t", workspace=self.tmp.name,
                               sandbox_policy=SandboxPolicy(),
                               extra={"project_dir": self.tmp.name})

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_reads_project_file(self):
        Path(self.tmp.name, "data.txt").write_text("PROJECT_DATA")
        r = tool("run_command").run({"argv": ["/bin/cat", "data.txt"]}, self.ctx)
        self.assertTrue(r.ok, r.content)
        self.assertIn("PROJECT_DATA", r.content)

    def test_run_can_write_project(self):
        r = tool("run_command").run(
            {"argv": ["/bin/sh", "-c", "echo made > out.txt"]}, self.ctx)
        self.assertTrue(r.ok, r.content)
        self.assertTrue(Path(self.tmp.name, "out.txt").exists())

    def test_empty_argv(self):
        r = tool("run_command").run({"argv": []}, self.ctx)
        self.assertFalse(r.ok)


class CodingLoopTests(unittest.TestCase):
    def test_write_python_and_run_it(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            script = [
                call("write_file",
                     {"path": "calc.py",
                      "content": "print(6 * 7)\n"}),
                call("run_command", {"argv": ["/usr/bin/python3", "calc.py"]}),
                say("Wrote calc.py and ran it; it prints 42."),
            ]
            agent = Agent(MockProvider(script), max_permission=Permission.WRITE)
            job = agent.run("Create calc.py that prints 6*7 and run it.",
                            project_dir=tmp.name)
            self.assertEqual(job.status, "completed")
            self.assertTrue(Path(tmp.name, "calc.py").exists())
            # run_command output (42) should be captured in the transcript
            self.assertTrue(any("42" in (m.get("content") or "")
                                for m in job.transcript))
            self.assertIn("write_file", agent.registry.names())
            self.assertIn("run_command", agent.registry.names())
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main(verbosity=2)
