"""Agent-tool wiring for the intelligence layer."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.builtins import default_tools  # noqa: E402
from reverseai.agent.evidence import EvidenceLog  # noqa: E402
from reverseai.agent.intelligence_tools import (  # noqa: E402
    AnalyzeDomainTool, BuildProofPackageTool, BuildWorldModelTool,
    CapabilityMapTool, DiscoverOpportunitiesTool, ExportToolManifestsTool,
    FormHypothesesTool, PlanDiscoveryMissionTool, PlanMissionTool,
    PlanProductTool, ProjectMemoryTool, QueryWorldModelTool,
    SearchArchitecturesTool,
    SelectModelTool, SimulateChangeTool, TrustCheckTool,
)
from reverseai.agent.tools import ToolContext  # noqa: E402
from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402

CC = shutil.which("cc") is not None


def _sandbox_ok() -> bool:
    try:
        create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        return True
    except Exception:
        return False


SANDBOX = _sandbox_ok()


def compile_fixture() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    src = Path(tmp.name) / "x.c"
    src.write_text(r"""
#include <stdio.h>
int main(void) { puts("hello"); return 0; }
""")
    out = Path(tmp.name) / "x"
    subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(out)],
                   check=True, capture_output=True)
    return tmp, out


class ToolRegistrationTests(unittest.TestCase):
    def test_intelligence_tools_are_unique_and_registered(self):
        names = [t.name for t in default_tools()]
        self.assertEqual(len(names), len(set(names)))
        for name in ("build_world_model", "discover_opportunities",
                     "query_world_model", "simulate_change",
                     "search_architectures", "plan_product", "select_model",
                     "build_proof_package", "plan_mission", "forge_tool",
                     "reality_check", "human_decision", "compression_plan",
                     "reconstruction_plan", "project_memory"):
            self.assertIn(name, names)


@unittest.skipUnless(CC, "cc unavailable")
class IntelligenceToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.bin = compile_fixture()
        cls.ctx = ToolContext(
            job_id="intel", workspace=str(Path(cls.tmp.name) / "work"),
            target_path=str(cls.bin),
            sandbox_policy=SandboxPolicy(allow_untrusted_execution=True),
            evidence=EvidenceLog(), goal="understand the program",
            extra={"all_tools": default_tools()})
        Path(cls.ctx.workspace).mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_world_build_query_and_discovery(self):
        res = BuildWorldModelTool().run({}, self.ctx)
        self.assertTrue(res.ok, res.content)
        self.assertGreater(res.data["summary"]["nodes"], 2)
        q = QueryWorldModelTool().run({"query": "summary"}, self.ctx)
        self.assertTrue(q.ok)
        d = DiscoverOpportunitiesTool().run({}, self.ctx)
        self.assertTrue(d.ok, d.content)
        self.assertGreaterEqual(d.data["summary"]["total"], 1)
        h = FormHypothesesTool().run({}, self.ctx)
        self.assertTrue(h.ok)
        plan = PlanDiscoveryMissionTool().run({"max_steps": 3}, self.ctx)
        self.assertTrue(plan.ok, plan.content)
        self.assertLessEqual(plan.data["plan"]["steps"], 3)

    def test_project_memory_round_trip(self):
        stored = ProjectMemoryTool().run(
            {"action": "store", "kind": "project",
             "text": "the export module owns CSV encoding",
             "scope": "project"}, self.ctx)
        self.assertTrue(stored.ok, stored.content)
        recalled = ProjectMemoryTool().run(
            {"action": "recall", "query": "CSV", "scope": "project"}, self.ctx)
        self.assertTrue(recalled.ok)
        self.assertEqual(len(recalled.data["entries"]), 1)
        entry_id = stored.data["entry"]["id"]
        invalid = ProjectMemoryTool().run(
            {"action": "invalidate", "entry_id": entry_id,
             "text": "decision was reversed"}, self.ctx)
        self.assertTrue(invalid.ok)
        after = ProjectMemoryTool().run(
            {"action": "recall", "query": "CSV", "scope": "project"}, self.ctx)
        self.assertEqual(after.data["entries"], [])

    def test_simulate_change(self):
        BuildWorldModelTool().run({}, self.ctx)
        res = SimulateChangeTool().run({"node": self.bin.name,
                                        "description": "remove text"}, self.ctx)
        self.assertTrue(res.ok, res.content)
        self.assertIn("hybrid_plan", res.data["simulation"])

    def test_architecture_product_router_mission_and_trust(self):
        arch = SearchArchitecturesTool().run({
            "candidates": [
                {"name": "A", "measurements": {"perf": 9, "cost": 8}},
                {"name": "B", "measurements": {"perf": 7, "cost": 3}}],
            "objectives": [{"name": "perf", "weight": 0.7},
                           {"name": "cost", "weight": 0.3,
                            "direction": "min"}]}, self.ctx)
        self.assertTrue(arch.ok, arch.content)
        product = PlanProductTool().run(
            {"goal": "Build a secure notes app for Linux. It must work offline."},
            self.ctx)
        self.assertTrue(product.ok)
        model = SelectModelTool().run({
            "task": "reason", "required": ["reason"],
            "profiles": [{"name": "small", "capabilities": ["code"],
                          "cost_per_mtok": 0.1, "latency_ms": 100},
                         {"name": "big", "capabilities": ["reason"],
                          "cost_per_mtok": 2, "latency_ms": 900}]}, self.ctx)
        self.assertTrue(model.ok)
        self.assertEqual(model.data["decision"]["profile"]["name"], "big")
        mission = PlanMissionTool().run(
            {"objective": "modernise", "budget_usd": 50}, self.ctx)
        self.assertTrue(mission.ok)
        self.assertTrue(mission.data["mission"].get("saved_to"))
        trust = TrustCheckTool().run(
            {"action": "deploy", "reversible": False,
             "blast_radius": "production"}, self.ctx)
        self.assertTrue(trust.ok)
        self.assertEqual(trust.data["trust"]["tier"], "forbid")

    def test_proof_manifest_capability_and_domain_tools(self):
        manifests = ExportToolManifestsTool().run({}, self.ctx)
        self.assertTrue(manifests.ok)
        self.assertGreater(len(manifests.data["manifests"]), 10)
        cmap = CapabilityMapTool().run({"records": [
            {"task_class": "elf_patch", "attempts": 5, "verified": 4,
             "tools": ["apply_byte_patch"]}]}, self.ctx)
        self.assertTrue(cmap.ok)
        self.assertTrue(cmap.data["capability"]["published"])
        dom = AnalyzeDomainTool().run({"domain": "security"}, self.ctx)
        self.assertTrue(dom.ok, dom.content)
        self.assertEqual(dom.data["adapter"]["kind"], "security")
        proof = BuildProofPackageTool().run(
            {"goal": "understand", "change": "none",
             "limitations": ["no behavioral change"]}, self.ctx)
        self.assertTrue(proof.ok, proof.content)
        self.assertTrue(Path(proof.data["files"]["manifest"]).is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
