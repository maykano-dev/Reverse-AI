"""Control-flow graph tests using a compiled fixture."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.core.cfg import analyze_control_flow, build_cfg  # noqa: E402
from reverseai.core.disasm import capstone_available  # noqa: E402

CC = shutil.which("cc") is not None
CS = capstone_available()


def compile_fixture() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    src = Path(tmp.name) / "cfg.c"
    src.write_text(r"""
#include <stdio.h>
int classify(int x) {
    if (x > 10) return 2;
    if (x == 0) return 0;
    return 1;
}
int main(int argc, char **argv) {
    printf("%d\n", classify(argc));
    for (int i = 0; i < 3; i++) puts("x");
    return 0;
}
""")
    out = Path(tmp.name) / "cfg"
    subprocess.run(["cc", "-no-pie", "-O0", str(src), "-o", str(out)],
                   check=True, capture_output=True)
    return tmp, out


class BlockTests(unittest.TestCase):
    def test_empty(self):
        graph = build_cfg([], "empty")
        self.assertEqual(graph.blocks, [])

    @unittest.skipUnless(CS, "capstone unavailable")
    def test_conditional_has_two_successors(self):
        from reverseai.core.disasm import Instruction

        insns = [
            Instruction(0x1000, "cmp", "eax, 10", 3, ""),
            Instruction(0x1003, "jle", "0x1010", 2, ""),
            Instruction(0x1005, "mov", "eax, 2", 5, ""),
            Instruction(0x100A, "jmp", "0x1015", 5, ""),
            Instruction(0x1010, "xor", "eax, eax", 2, ""),
            Instruction(0x1012, "ret", "", 1, ""),
            Instruction(0x1015, "ret", "", 1, ""),
        ]
        graph = build_cfg(insns, "cond")
        self.assertGreaterEqual(len(graph.blocks), 4)
        first = graph.blocks[0]
        self.assertEqual(first.terminator, "jle 0x1010")
        self.assertEqual(len(first.successors), 2)


@unittest.skipUnless(CC and CS, "cc or capstone unavailable")
class FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp, cls.binary = compile_fixture()
        cls.flow = analyze_control_flow(str(cls.binary), max_functions=16)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_functions_are_graphed(self):
        names = {f.name for f in self.flow.functions}
        self.assertIn("classify", names)
        self.assertIn("main", names)
        self.assertGreater(self.flow.to_dict()["block_count"], 5)

    def test_classify_has_branches(self):
        classify = next(f for f in self.flow.functions if f.name == "classify")
        self.assertGreaterEqual(len(classify.blocks), 4)
        self.assertGreater(classify.edges, len(classify.blocks))
        self.assertGreater(classify.cyclomatic_complexity, 1)
        self.assertTrue(any(b.successors for b in classify.blocks))

    def test_call_graph_has_targets(self):
        main = next(f for f in self.flow.functions if f.name == "main")
        self.assertTrue(main.calls)
        self.assertTrue(any(c.get("target") for c in main.calls))


if __name__ == "__main__":
    unittest.main(verbosity=2)
