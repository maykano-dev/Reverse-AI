"""Contract tests for every registered tool.

A tool is a public interface. It must:

* have a unique, snake_case name and a JSON-serializable schema;
* declare a valid permission tier and a security boundary;
* return a ToolResult (never raise) when called with missing arguments;
* have a human narration entry and a UI label.

Missing-argument behavior matters: a model can emit a partial call, and a
KeyError escaping the mediator is a reliability bug, not a model error.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.builtins import default_tools  # noqa: E402
from reverseai.agent.evidence import EvidenceLog  # noqa: E402
from reverseai.agent.narrative import describe_tool  # noqa: E402
from reverseai.agent.tools import Permission, ToolContext, ToolResult  # noqa: E402
from reverseai.intelligence.orchestration import ToolManifest  # noqa: E402
from reverseai.sandbox import SandboxPolicy  # noqa: E402


class ToolContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = default_tools()
        cls.names = {t.name for t in cls.tools}
        cls.ctx_tmp = tempfile.TemporaryDirectory()
        cls.ctx = ToolContext(
            job_id="contract",
            workspace=cls.ctx_tmp.name,
            target_path=None,
            sandbox_policy=SandboxPolicy(allow_untrusted_execution=True),
            evidence=EvidenceLog(),
            goal="",
            extra={"all_tools": cls.tools},
        )

    @classmethod
    def tearDownClass(cls):
        cls.ctx_tmp.cleanup()

    def test_names_are_unique_and_well_formed(self):
        self.assertEqual(len(self.names), len(self.tools))
        for tool in self.tools:
            self.assertRegex(tool.name, r"^[a-z][a-z0-9_]{2,64}$", tool.name)
            self.assertTrue(tool.description.strip(), tool.name)

    def test_specs_are_json_serializable(self):
        for tool in self.tools:
            spec = tool.spec()
            self.assertEqual(spec["type"], "function")
            self.assertEqual(spec["function"]["name"], tool.name)
            json.dumps(spec)  # must not raise
            self.assertIsInstance(spec["function"]["parameters"], dict)

    def test_permissions_are_valid(self):
        for tool in self.tools:
            self.assertIsInstance(tool.permission, Permission)
            self.assertIn(tool.permission.label,
                          {"read", "execute", "write", "dangerous"})

    def test_manifests_are_valid(self):
        from reverseai.intelligence.orchestration import validate_manifest

        for tool in self.tools:
            manifest = ToolManifest.from_tool(tool).to_dict()
            self.assertEqual(validate_manifest(manifest), [], tool.name)
            self.assertTrue(manifest["security_boundary"], tool.name)

    def test_narration_exists_for_every_tool(self):
        for tool in self.tools:
            info = describe_tool(tool.name, {})
            self.assertTrue(info["title"].strip(), tool.name)
            self.assertTrue(info["detail"].strip(), tool.name)
            self.assertTrue(info["icon"].strip(), tool.name)

    def test_ui_label_exists_for_every_tool(self):
        app = Path(__file__).resolve().parent.parent / "reverseai/server/static/app.js"
        text = app.read_text(encoding="utf-8")
        for tool in self.tools:
            # Labels are written as `name: "..."` in the TOOL_LABEL map.
            self.assertRegex(text, re.escape(tool.name) + r"\s*:", tool.name)

    def test_every_tool_returns_a_result_with_empty_arguments(self):
        problems = []
        for tool in self.tools:
            try:
                result = tool.run({}, self.ctx)
            except Exception as exc:  # noqa: BLE001 - this is the contract
                problems.append(f"{tool.name}: raised {type(exc).__name__}: {exc}")
                continue
            if not isinstance(result, ToolResult):
                problems.append(f"{tool.name}: returned {type(result).__name__}")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_write_tools_do_not_succeed_on_empty_arguments(self):
        # A write tool must not silently create or alter anything without its
        # required parameters.
        # These two have a valid default action with empty arguments:
        # a checkpoint with a generated label, and a memory recall.
        optional_defaults = {"create_workspace_checkpoint", "project_memory"}
        for tool in self.tools:
            if tool.permission < Permission.WRITE:
                continue
            if tool.name in optional_defaults:
                continue
            result = tool.run({}, self.ctx)
            self.assertFalse(result.ok, tool.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
