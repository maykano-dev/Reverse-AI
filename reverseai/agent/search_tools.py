"""Agent tool for deterministic MCTS over an explicit plan graph."""

from __future__ import annotations

from .mcts import MCTS
from .tools import Permission, Tool, ToolResult


class SearchPlanTool(Tool):
    name = "search_plan"
    description = (
        "Run Monte Carlo tree search over an explicit plan graph and return the "
        "most-visited path. Nodes map ids to {actions:[{id,to,label}], value, "
        "terminal}. Use it when several plans have deterministic scores and you "
        "want test-time search instead of a linear guess."
    )
    parameters = {
        "type": "object",
        "properties": {
            "root": {"type": "string"},
            "nodes": {"type": "object"},
            "iterations": {"type": "integer", "minimum": 1,
                           "maximum": 20000, "default": 500},
            "exploration": {"type": "number", "minimum": 0, "maximum": 10,
                            "default": 1.414},
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 100,
                          "default": 30},
        },
        "required": ["root", "nodes"],
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        root = str(args.get("root") or "").strip()
        nodes = args.get("nodes")
        if not root or not isinstance(nodes, dict) or not nodes:
            return ToolResult.failure("root and a non-empty nodes object are required")
        if root not in nodes:
            return ToolResult.failure(f"root node not found: {root}")

        def actions(state):
            node = nodes.get(state) or {}
            out = []
            for a in node.get("actions") or []:
                if isinstance(a, dict) and a.get("to") in nodes:
                    out.append(a)
            return out

        def advance(state, action):
            return action["to"]

        def evaluate(state):
            node = nodes.get(state) or {}
            try:
                return float(node.get("value", 0.0) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        try:
            result = MCTS(actions, advance, evaluate,
                          exploration=float(args.get("exploration", 1.414)),
                          max_depth=int(args.get("max_depth", 30))).run(
                              root, int(args.get("iterations", 500)))
        except Exception as exc:
            return ToolResult.failure(f"search failed: {exc}")
        labels = []
        for step in result["path"]:
            action = step["action"] if isinstance(step["action"], dict) else {}
            labels.append(action.get("label") or action.get("id") or step["state"])
        result["labels"] = labels
        body = " -> ".join(labels) if labels else "(root only)"
        return ToolResult.success(
            f"best path: {body}\nvalue={result['best_value']} "
            f"iterations={result['iterations']}",
            **result)


def search_tools() -> list[Tool]:
    return [SearchPlanTool()]
