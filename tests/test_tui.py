"""Tests for the interactive terminal (TUI)."""

from __future__ import annotations

import builtins
import io
import tempfile
import unittest
from contextlib import redirect_stdout

from reverseai.tui import TUI, _C


def _tui():
    return TUI(provider="mock", permission="read")


class LabelTests(unittest.TestCase):
    def test_plan_label_variants(self):
        self.assertEqual(TUI._plan_label({"title": "A", "detail": "x"}), "A")
        self.assertEqual(TUI._plan_label(("B", "y")), "B")
        self.assertEqual(TUI._plan_label("C"), "C")


class ColorTests(unittest.TestCase):
    def test_nocolor_is_plain(self):
        c = _C(False)
        self.assertEqual(c.bold("hi"), "hi")
        self.assertIn("hi", c.accent("hi"))

    def test_color_wraps(self):
        c = _C(True)
        self.assertIn("\033[", c.bold("hi"))


class CommandTests(unittest.TestCase):
    def test_exit_returns_false(self):
        t = _tui()
        self.assertFalse(t._command("/exit"))
        self.assertFalse(t._command("/quit"))

    def test_unknown_command(self):
        t = _tui()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertTrue(t._command("/nope"))
        self.assertIn("unknown command", buf.getvalue())

    def test_help_lists_commands(self):
        t = _tui()
        buf = io.StringIO()
        with redirect_stdout(buf):
            t._command("/help")
        out = buf.getvalue()
        for cmd in ("/clear", "/cost", "/compact", "/undo", "/doctor", "/project", "/mode"):
            self.assertIn(cmd, out)

    def test_cost_reports_session(self):
        t = _tui()
        buf = io.StringIO()
        with redirect_stdout(buf):
            t._command("/cost")
        self.assertIn("tokens", buf.getvalue())

    def test_doctor_runs(self):
        t = _tui()
        buf = io.StringIO()
        with redirect_stdout(buf):
            t._command("/doctor")
        out = buf.getvalue()
        self.assertIn("provider: mock", out)
        self.assertIn("sandbox", out)

    def test_mode_set_and_show(self):
        t = _tui()
        buf = io.StringIO()
        with redirect_stdout(buf):
            t._command("/mode build")
        self.assertEqual(t.mode, "build")
        buf = io.StringIO()
        with redirect_stdout(buf):
            t._command("/mode bogus")
        self.assertIn("unknown mode", buf.getvalue())

    def test_project_valid_and_invalid(self):
        t = _tui()
        d = tempfile.mkdtemp()
        buf = io.StringIO()
        with redirect_stdout(buf):
            t._command(f"/project {d}")
        self.assertEqual(t.project_dir, str(__import__("pathlib").Path(d).resolve()))
        buf = io.StringIO()
        with redirect_stdout(buf):
            t._command("/project /no/such/folder/xyz")
        self.assertIn("no such folder", buf.getvalue())


class EventRenderTests(unittest.TestCase):
    def test_reason_and_error_render(self):
        t = _tui()
        buf = io.StringIO()
        with redirect_stdout(buf):
            t._on_event({"type": "plan", "steps": [{"title": "Understand"}]})
            t._on_event({"type": "reason", "title": "Opening the file", "icon": "file"})
            t._on_event({"type": "tool_result", "name": "x", "ok": False, "content": "boom"})
            t._on_event({"type": "error", "error": "nope"})
        out = buf.getvalue()
        self.assertIn("Understand", out)
        self.assertIn("Opening the file", out)
        self.assertIn("boom", out)
        self.assertIn("nope", out)

    def test_accumulate_usage(self):
        t = _tui()
        t._accumulate({"total_tokens": 1200, "cost_usd": 0.01})
        self.assertGreaterEqual(t._usage["cost"], 0.01)


class ReplIntegrationTests(unittest.TestCase):
    def test_run_processes_turn_then_exits(self):
        t = _tui()
        lines = iter(["say hi", "/cost", "/exit"])

        def fake_input(prompt=""):
            try:
                return next(lines)
            except StopIteration:
                raise EOFError

        orig = builtins.input
        builtins.input = fake_input
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = t.run()
        finally:
            builtins.input = orig
        self.assertEqual(rc, 0)
        self.assertIn("bye.", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
