"""Small deterministic Monte Carlo tree search for branching plans.

The engine is generic: callers provide legal actions, a transition function,
and a terminal/leaf evaluator. The agent-facing tool uses an explicit graph
spec, so the search is reproducible and does not pretend to execute untrusted
code. The same engine can later be wired to sandbox coverage or test rewards.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Hashable


@dataclass
class Node:
    state: Hashable
    parent: "Node | None" = None
    action: Any = None
    children: list["Node"] = field(default_factory=list)
    visits: int = 0
    value: float = 0.0
    untried: list[Any] = field(default_factory=list)


class MCTS:
    def __init__(self, actions_fn: Callable[[Hashable], list[Any]],
                 transition_fn: Callable[[Hashable, Any], Hashable],
                 evaluate_fn: Callable[[Hashable], float], *,
                 exploration: float = 1.414, max_depth: int = 30,
                 seed: int = 7) -> None:
        self.actions_fn = actions_fn
        self.transition_fn = transition_fn
        self.evaluate_fn = evaluate_fn
        self.exploration = max(0.0, float(exploration))
        self.max_depth = max(1, int(max_depth))
        self.random = random.Random(seed)

    def _expand(self, node: Node) -> Node | None:
        if not node.untried:
            return None
        action = node.untried.pop(0)
        child = Node(self.transition_fn(node.state, action), node, action)
        child.untried = list(self.actions_fn(child.state))
        node.children.append(child)
        return child

    def _select(self, node: Node) -> Node:
        while not node.untried and node.children:
            node = max(node.children, key=self._uct)
        return node

    def _uct(self, node: Node) -> float:
        parent = node.parent
        if parent is None or node.visits == 0:
            return float("inf")
        explore = self.exploration * (
            (2.0 * (parent.visits ** 0.5)) / (1.0 + node.visits))
        return node.value / node.visits + explore

    def _simulate(self, state: Hashable, depth: int) -> float:
        seen = set()
        for _ in range(max(1, self.max_depth - depth)):
            actions = self.actions_fn(state)
            if not actions:
                break
            # Deterministic rollout: first action, avoiding cycles when possible.
            choice = None
            for action in actions:
                nxt = self.transition_fn(state, action)
                if nxt not in seen:
                    choice = action
                    break
            if choice is None:
                break
            state = self.transition_fn(state, choice)
            seen.add(state)
        return float(self.evaluate_fn(state))

    def _backprop(self, node: Node, value: float) -> None:
        while node is not None:
            node.visits += 1
            node.value += value
            node = node.parent

    def run(self, root_state: Hashable, iterations: int = 500) -> dict[str, Any]:
        root = Node(root_state)
        root.untried = list(self.actions_fn(root_state))
        for _ in range(max(1, int(iterations))):
            node = self._select(root)
            depth = 0
            cursor = node
            while cursor.parent is not None:
                depth += 1
                cursor = cursor.parent
            if depth < self.max_depth:
                child = self._expand(node)
                if child is not None:
                    node = child
            value = self._simulate(node.state, depth)
            self._backprop(node, value)
        path = []
        cursor = root
        while cursor.children:
            cursor = max(cursor.children, key=lambda n: n.visits)
            path.append({"action": cursor.action, "state": cursor.state,
                         "visits": cursor.visits,
                         "value": round(cursor.value / max(1, cursor.visits), 6)})
        return {
            "root": root_state,
            "iterations": max(1, int(iterations)),
            "path": path,
            "best_value": round(self.evaluate_fn(cursor.state), 6),
            "root_visits": root.visits,
        }
