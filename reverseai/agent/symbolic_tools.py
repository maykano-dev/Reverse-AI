"""Agent tool for deterministic constraint solving."""

from __future__ import annotations

import json

from ..symbolic import SymbolicError, solve
from .tools import Permission, Tool, ToolResult


class SolveConstraintsTool(Tool):
    name = "solve_constraints"
    description = (
        "Solve exact integer/bitwise constraints with a deterministic solver. "
        "Use it for checksum/flag/password-style checks instead of guessing. "
        "Constraints are {op,left,right} with op eq/ne/lt/le/gt/ge and "
        "expressions var/const/add/sub/mul/xor/and/or/shl/shr/mod. Z3 is used "
        "when installed; otherwise finite ranges are enumerated honestly."
    )
    parameters = {
        "type": "object",
        "properties": {
            "constraints": {"type": "array", "items": {"type": "object"}},
            "variables": {"type": ["object", "array", "null"]},
            "bits": {"type": "integer", "minimum": 1, "maximum": 128,
                     "default": 64},
            "max_candidates": {"type": "integer", "minimum": 1,
                               "maximum": 2000000, "default": 200000},
            "timeout": {"type": "number", "minimum": 0.05, "maximum": 30,
                        "default": 2.0},
        },
        "required": ["constraints"],
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        try:
            result = solve(
                args.get("constraints") or [],
                args.get("variables"),
                bits=int(args.get("bits", 64) or 64),
                max_candidates=int(args.get("max_candidates", 200000) or 200000),
                timeout=float(args.get("timeout", 2.0) or 2.0),
            )
        except (SymbolicError, TypeError, ValueError) as exc:
            return ToolResult.failure(f"constraint error: {exc}")
        body = json.dumps(result.to_dict(), indent=2)
        return ToolResult.success(
            f"{result.status} via {result.method}\n{body}",
            **result.to_dict())


def symbolic_tools() -> list[Tool]:
    return [SolveConstraintsTool()]
