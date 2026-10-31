"""Deterministic constraint solving and its agent tool."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.symbolic_tools import SolveConstraintsTool  # noqa: E402
from reverseai.agent.tools import ToolContext  # noqa: E402
from reverseai.symbolic import SymbolicError, solve  # noqa: E402


class SolverTests(unittest.TestCase):
    def test_linear_constraint(self):
        result = solve(
            [{"op": "eq", "left": {"add": [{"var": "x"}, {"const": 3}]},
              "right": {"const": 10}}],
            {"x": {"min": 0, "max": 20}}, bits=8)
        self.assertEqual(result.status, "sat")
        self.assertEqual(result.model["x"], 7)

    def test_bitwise_xor_constraint(self):
        result = solve(
            [{"op": "eq", "left": {"xor": [{"var": "x"}, {"const": 42}]},
              "right": {"const": 85}}],
            {"x": {"min": 0, "max": 255}}, bits=8)
        self.assertEqual(result.status, "sat")
        self.assertEqual(result.model["x"], 127)

    def test_unsatisfiable_constraints(self):
        result = solve([
            {"op": "gt", "left": {"var": "x"}, "right": {"const": 10}},
            {"op": "lt", "left": {"var": "x"}, "right": {"const": 5}},
        ], {"x": {"min": 0, "max": 20}}, bits=8)
        self.assertEqual(result.status, "unsat")

    def test_oversized_domain_is_unknown_not_false(self):
        result = solve(
            [{"op": "eq", "left": {"var": "x"}, "right": {"const": 999}}],
            {"x": {"min": 0, "max": 100000}}, max_candidates=10, bits=32)
        self.assertEqual(result.status, "unknown")
        self.assertIn("z3", result.reason)

    def test_invalid_expression_is_refused(self):
        with self.assertRaises(SymbolicError):
            solve([{"op": "eq", "left": {"wat": 1}, "right": {"const": 2}}],
                  {"x": {"min": 0, "max": 1}})


class SolverToolTests(unittest.TestCase):
    def test_tool_returns_a_model(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = ToolContext(job_id="s", workspace=td)
            result = SolveConstraintsTool().run({
                "constraints": [
                    {"op": "eq", "left": {"xor": [{"var": "key"}, {"const": 1}]},
                     "right": {"const": 8}},
                ],
                "variables": {"key": {"min": 0, "max": 15}},
                "bits": 8,
            }, ctx)
        self.assertTrue(result.ok, result.content)
        self.assertEqual(result.data["model"]["key"], 9)

    def test_empty_constraints_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = ToolContext(job_id="s", workspace=td)
            result = SolveConstraintsTool().run({}, ctx)
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
