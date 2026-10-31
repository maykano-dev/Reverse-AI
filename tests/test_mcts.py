"""Deterministic MCTS engine and plan-graph tool."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.mcts import MCTS  # noqa: E402
from reverseai.agent.search_tools import SearchPlanTool  # noqa: E402
from reverseai.agent.tools import ToolContext  # noqa: E402

GRAPH = {
    "root": {"actions": [
        {"id": "safe", "to": "a", "label": "safe path"},
        {"id": "best", "to": "b", "label": "high-value path"},
    ], "value": 0},
    "a": {"actions": [], "value": 0.2},
    "b": {"actions": [{"id": "finish", "to": "c", "label": "finish"}], "value": 0.5},
    "c": {"actions": [], "value": 1.0},
}


class MCTSTests(unittest.TestCase):
    def test_search_finds_the_high_value_branch(self):
        def actions(state):
            return (GRAPH.get(state) or {}).get("actions") or []
        def advance(_state, action):
            return action["to"]
        def value(state):
            return float((GRAPH.get(state) or {}).get("value", 0.0))
        result = MCTS(actions, advance, value, seed=1).run("root", 300)
        self.assertTrue(result["path"])
        self.assertEqual(result["path"][0]["state"], "b")
        self.assertEqual(result["labels"] if "labels" in result else
                         [step["action"]["label"] for step in result["path"]],
                         ["high-value path", "finish"])

    def test_tool_returns_labels_and_value(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = ToolContext(job_id="m", workspace=td)
            res = SearchPlanTool().run(
                {"root": "root", "nodes": GRAPH, "iterations": 250}, ctx)
        self.assertTrue(res.ok, res.content)
        self.assertEqual(res.data["labels"][0], "high-value path")
        self.assertEqual(res.data["best_value"], 1.0)

    def test_empty_tool_args_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            res = SearchPlanTool().run({}, ToolContext(job_id="m", workspace=td))
        self.assertFalse(res.ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
