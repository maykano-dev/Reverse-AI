"""Agent-layer tests — tools, mediator, evidence, and the full loop via mock LLM.

Run: python3 -m unittest tests.test_agent -v
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent import (  # noqa: E402
    Agent,
    Confidence,
    EvidenceLog,
    Permission,
    ToolContext,
    ToolMediator,
    ToolRegistry,
    default_tools,
)
from reverseai.agent.providers.base import Message, Role  # noqa: E402
from reverseai.agent.providers.mock import MockProvider, call, say  # noqa: E402
from reverseai.agent.tools import Tool, ToolResult  # noqa: E402


def compile_hello() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    src = Path(tmp.name) / "hello.c"
    src.write_text('#include <stdio.h>\nint main(){puts("AGENT_MARKER");return 0;}\n')
    out = Path(tmp.name) / "hello"
    subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(out)],
                   check=True, capture_output=True)
    return tmp, out


class EvidenceTests(unittest.TestCase):
    def test_tiers_and_summary(self):
        log = EvidenceLog()
        log.believed("maybe packed")
        log.observed("elf x86_64")
        log.verified("runs and prints marker")
        self.assertEqual(log.summary(),
                         {"believed": 1, "observed": 1, "verified": 1})
        self.assertEqual(len(log.at_least(Confidence.OBSERVED)), 2)


class _DangerTool(Tool):
    name = "danger"
    description = "x"
    permission = Permission.DANGEROUS

    def run(self, args, ctx):
        return ToolResult.success("should not run")


class _BoomTool(Tool):
    name = "boom"
    description = "x"
    permission = Permission.READ

    def run(self, args, ctx):
        raise RuntimeError("kaboom")


class MediatorTests(unittest.TestCase):
    def setUp(self):
        self.reg = ToolRegistry()
        self.reg.register_all(default_tools())
        self.reg.register(_DangerTool())
        self.reg.register(_BoomTool())
        self.ctx = ToolContext(job_id="t", workspace="/tmp", evidence=EvidenceLog())

    def test_above_ceiling_refused(self):
        med = ToolMediator(self.reg, max_permission=Permission.EXECUTE)
        res = med.dispatch("danger", {}, self.ctx)
        self.assertFalse(res.ok)
        self.assertIn("Refused", res.content)
        self.assertFalse(med.audit[-1].allowed)

    def test_confirm_can_allow(self):
        med = ToolMediator(self.reg, max_permission=Permission.EXECUTE,
                           confirm=lambda *a: True)
        res = med.dispatch("danger", {}, self.ctx)
        self.assertTrue(res.ok)

    def test_execute_refused_under_read_ceiling(self):
        med = ToolMediator(self.reg, max_permission=Permission.READ)
        res = med.dispatch("run_in_sandbox", {}, self.ctx)
        self.assertFalse(res.ok)

    def test_tool_exception_contained(self):
        med = ToolMediator(self.reg, max_permission=Permission.READ)
        res = med.dispatch("boom", {}, self.ctx)
        self.assertFalse(res.ok)
        self.assertIn("RuntimeError", res.error)

    def test_unknown_tool(self):
        med = ToolMediator(self.reg)
        res = med.dispatch("nope", {}, self.ctx)
        self.assertFalse(res.ok)

    def test_missing_required_arg(self):
        med = ToolMediator(self.reg, max_permission=Permission.READ)
        res = med.dispatch("read_bytes", {"offset": 0}, self.ctx)  # missing length
        self.assertFalse(res.ok)
        self.assertIn("length", res.error)


class MessageSerializationTests(unittest.TestCase):
    def test_tool_message_roundtrip(self):
        m = Message(Role.TOOL, content="result", tool_call_id="c1", name="analyze_binary")
        d = m.to_openai()
        self.assertEqual(d["role"], "tool")
        self.assertEqual(d["tool_call_id"], "c1")


class RegistryTests(unittest.TestCase):
    def test_provider_specs_shape(self):
        reg = ToolRegistry()
        reg.register_all(default_tools())
        specs = reg.provider_specs()
        self.assertTrue(all(s["type"] == "function" for s in specs))
        names = {s["function"]["name"] for s in specs}
        self.assertIn("analyze_binary", names)
        self.assertIn("run_in_sandbox", names)

    def test_no_duplicate(self):
        reg = ToolRegistry()
        reg.register_all(default_tools())
        with self.assertRaises(ValueError):
            reg.register(default_tools()[0])


class FullLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.tmp, cls.bin = compile_hello()
            cls.compiled = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            cls.compiled = False

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "compiled", False):
            cls.tmp.cleanup()

    def setUp(self):
        if not self.compiled:
            self.skipTest("cc unavailable")

    def test_investigation_to_verified_conclusion(self):
        script = [
            call("host_capabilities", {}),
            call("analyze_binary", {}),
            call("run_in_sandbox", {"args": []}),
            call("record_finding",
                 {"claim": "prints AGENT_MARKER on run", "confidence": "verified"}),
            say("Verified: the program runs in the sandbox and prints AGENT_MARKER."),
        ]
        agent = Agent(MockProvider(script), max_permission=Permission.EXECUTE)
        job = agent.run("Confirm what this program does when executed.",
                        target_path=str(self.bin))

        self.assertEqual(job.status, "completed")
        self.assertIn("AGENT_MARKER", job.final_answer)
        # analyze_binary -> observed; run_in_sandbox + record_finding -> verified
        summary = job.evidence.summary()
        self.assertGreaterEqual(summary["observed"], 1)
        self.assertGreaterEqual(summary["verified"], 1)
        # audit recorded each dispatched tool
        tools_called = {e.tool for e in agent.mediator.audit}
        self.assertIn("run_in_sandbox", tools_called)
        # transcript round-trips to OpenAI format
        self.assertTrue(all("role" in m for m in job.transcript))

    def test_report_separates_tiers(self):
        script = [
            call("analyze_binary", {}),
            say("Done."),
        ]
        agent = Agent(MockProvider(script), max_permission=Permission.READ)
        job = agent.run("Analyze.", target_path=str(self.bin))
        report = job.report()
        self.assertIn("observed", report)
        self.assertIn("Conclusion", report)

    def test_refuses_missing_target(self):
        agent = Agent(MockProvider([say("x")]))
        job = agent.run("do a thing", target_path="/nonexistent/path/xyz")
        self.assertEqual(job.status, "refused")
        self.assertIn("rejected", job.error)


if __name__ == "__main__":
    unittest.main(verbosity=2)
