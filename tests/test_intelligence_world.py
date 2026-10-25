"""World model, engineering graph, memory fabric, and analysis seeding."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.core import analyze_file  # noqa: E402
from reverseai.core.models import AnalysisReport, Arch, BinaryFormat, Section  # noqa: E402
from reverseai.intelligence.world import (  # noqa: E402
    MemoryFabric, WorldModel, WorldModelError, world_from_analysis,
)

CC = shutil.which("cc") is not None


def synthetic_report() -> AnalysisReport:
    return AnalysisReport(
        path="sample.bin", size=4096, fmt=BinaryFormat.ELF,
        arch=Arch.X86_64, bits=64, entry_point=0x401000,
        sections=[Section(".text", 0x401000, 0x200, 0x200, 0x1000, 6.1, "rx"),
                  Section(".rodata", 0x402000, 0x100, 0x100, 0x1200, 7.4, "r")],
        imports={"libc.so.6": ["puts", "system"]},
        exports=["main"], functions=[{"name": "main", "address": 0x401000,
                                      "size": 64}],
        strings_sample=["debug menu", "https://api.example.test"],
        string_count=2,
    )


class WorldModelTests(unittest.TestCase):
    def test_nodes_edges_and_provenance(self):
        wm = WorldModel("demo")
        a = wm.add_node("component", "api", confidence="observed",
                        source="test", detail="parsed")
        b = wm.add_node("service", "db", confidence="hypothesis")
        wm.add_edge(a.id, b.id, "depends_on")
        self.assertEqual(wm.neighbors(a.id)[0].name, "db")
        self.assertEqual(wm.descendants(a.id)[0].name, "db")
        self.assertEqual(wm.ancestors(b.id)[0].name, "api")
        self.assertIn("db", [n.name for n in wm.weak_components()])

    def test_records_and_queries(self):
        wm = WorldModel("demo")
        comp = wm.add_node("component", "export")
        req = wm.add_record("requirement", "CSV exports are correct",
                            links=[comp.id], confidence="observed")
        test = wm.add_record("test", "export test", links=[comp.id])
        self.assertEqual(wm.unverified_requirements()[0].id, req.id)
        self.assertEqual(len(wm.next_best_tests()), 1)
        wm.set_record_status(test.id, "verified")
        self.assertEqual(wm.next_best_tests(), [])
        wm.set_record_status(req.id, "verified")
        self.assertEqual(wm.unverified_requirements(), [])

    def test_invalidate_and_stale(self):
        wm = WorldModel()
        n = wm.add_node("component", "old")
        self.assertTrue(wm.invalidate(n.id, "removed in v2"))
        self.assertEqual(wm.nodes[n.id].provenance.invalidated_by, "removed in v2")
        self.assertTrue(wm.stale())

    def test_unknown_record_kind_is_refused(self):
        with self.assertRaises(WorldModelError):
            WorldModel().add_record("nonsense", "x")

    def test_save_load_merge(self):
        with tempfile.TemporaryDirectory() as td:
            wm = WorldModel("one")
            a = wm.add_node("component", "a")
            wm.add_record("decision", "use a", links=[a.id])
            p = wm.save(Path(td) / "world.json")
            loaded = WorldModel.load(p)
            self.assertEqual(loaded.summary()["nodes"], 1)
            other = WorldModel("two")
            other.add_node("component", "b")
            loaded.merge(other)
            self.assertEqual(loaded.summary()["nodes"], 2)

    def test_world_from_real_analysis(self):
        report = synthetic_report()
        wm = world_from_analysis(report)
        self.assertEqual(wm.name, "sample.bin")
        self.assertTrue(wm.find(kind="section", name="text"))
        self.assertTrue(wm.find(kind="dependency", name="libc"))
        self.assertTrue(wm.find(kind="function", name="main"))
        self.assertGreaterEqual(wm.summary()["unresolved"], 1)
        self.assertIn("target", wm.summary()["node_kinds"])

    @unittest.skipUnless(CC, "cc unavailable")
    def test_world_from_compiled_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "x.c"
            src.write_text('#include <stdio.h>\nint main(){puts("x");return 0;}\n')
            out = Path(td) / "x"
            subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(out)],
                           check=True, capture_output=True)
            wm = world_from_analysis(analyze_file(out))
            self.assertTrue(wm.find(kind="target"))
            self.assertTrue(wm.find(kind="section", name=".text"))


class MemoryFabricTests(unittest.TestCase):
    def test_memory_classes_and_scope(self):
        mf = MemoryFabric("proj")
        mf.store("episodic", "ran a failed patch", scope="proj")
        mf.store("procedural", "how to capture a corpus", scope="global")
        mf.store("causal", "the timeout was caused by DNS", scope="other")
        self.assertEqual(len(mf.recall("", kind="episodic")), 1)
        self.assertEqual(len(mf.recall("", scope="proj")), 2)
        self.assertEqual(len(mf.recall("", scope="global")), 1)

    def test_invalidate_and_persist(self):
        with tempfile.TemporaryDirectory() as td:
            mf = MemoryFabric("p")
            row = mf.store("evaluation", "model A did better on unseen tasks")
            mf.invalidate(row["id"], "holdout was leaked")
            self.assertEqual(mf.recall(""), [])
            p = mf.save(Path(td) / "mem.json")
            self.assertEqual(MemoryFabric.load(p).name, "p")


if __name__ == "__main__":
    unittest.main(verbosity=2)
