"""Explicit causal graphs and bounded counterfactuals.

A correlation is not a cause. This module only makes a causal prediction when
the caller supplied a mechanism (a function) or an experiment established the
edge. Otherwise the answer is ``unknown`` with the missing evidence named.

The graph is intentionally small and serializable; mechanisms live in a separate
runtime map because they are code, not data.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

CONFIDENCE = ("hypothesis", "observed", "established")
Mechanism = Callable[[dict[str, Any]], Any]


class CausalError(Exception):
    pass


@dataclass
class CausalNode:
    name: str
    baseline: Any = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CausalEdge:
    cause: str
    effect: str
    confidence: str = "hypothesis"
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Counterfactual:
    outcome: str
    predicted: Any = None
    status: str = "unknown"       # predicted | unknown | inconsistent
    reason: str = ""
    assumptions: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CausalGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, CausalNode] = {}
        self.edges: list[CausalEdge] = []
        self.mechanisms: dict[str, Mechanism] = {}

    def add_node(self, name: str, baseline: Any = None,
                 description: str = "") -> CausalNode:
        node = self.nodes.get(name)
        if node is None:
            node = CausalNode(name, baseline, description[:1000])
            self.nodes[name] = node
        elif baseline is not None:
            node.baseline = baseline
        return node

    def add_edge(self, cause: str, effect: str, *,
                 confidence: str = "hypothesis", evidence: str = "") -> CausalEdge:
        if cause not in self.nodes or effect not in self.nodes:
            raise CausalError("both endpoints must exist")
        if confidence not in CONFIDENCE:
            raise CausalError(f"unknown confidence: {confidence}")
        edge = CausalEdge(cause, effect, confidence, evidence[:2000])
        self.edges.append(edge)
        return edge

    def set_mechanism(self, name: str, fn: Mechanism) -> None:
        if name not in self.nodes:
            raise CausalError("mechanism needs an existing node")
        self.mechanisms[name] = fn

    def parents(self, name: str) -> list[str]:
        return [e.cause for e in self.edges if e.effect == name]

    def children(self, name: str) -> list[str]:
        return [e.effect for e in self.edges if e.cause == name]

    def topological(self) -> list[str]:
        indeg = {n: 0 for n in self.nodes}
        for e in self.edges:
            indeg[e.effect] += 1
        queue = [n for n, d in indeg.items() if d == 0]
        out = []
        while queue:
            n = queue.pop(0)
            out.append(n)
            for c in self.children(n):
                indeg[c] -= 1
                if indeg[c] == 0:
                    queue.append(c)
        if len(out) != len(self.nodes):
            raise CausalError("the causal graph has a cycle")
        return out

    def _strong_enough(self, edge: CausalEdge) -> bool:
        return edge.confidence in ("observed", "established")

    def intervene(self, target: str, value: Any) -> dict[str, Any]:
        """Set a node and propagate only through known mechanisms.

        A missing mechanism produces ``unknown`` for that descendant. We do not
        fill the gap with a language-model guess.
        """
        if target not in self.nodes:
            raise CausalError("intervention target does not exist")
        values: dict[str, Any] = {n: self.nodes[n].baseline for n in self.nodes}
        values[target] = value
        unknown: list[str] = []
        unknown_set: set[str] = set()
        assumptions = [f"{target} is set by intervention (do({target}={value!r}))"]
        for name in self.topological():
            if name == target:
                continue
            parent_names = self.parents(name)
            if not parent_names:
                continue
            if any(p in unknown_set for p in parent_names):
                unknown.append(name)
                unknown_set.add(name)
                continue
            edges = [e for e in self.edges if e.effect == name]
            if not all(self._strong_enough(e) for e in edges):
                unknown.append(name)
                unknown_set.add(name)
                continue
            fn = self.mechanisms.get(name)
            if fn is None:
                unknown.append(name)
                unknown_set.add(name)
                continue
            try:
                values[name] = fn(values)
            except Exception as exc:
                unknown.append(f"{name} ({type(exc).__name__}: {exc})")
                unknown_set.add(name)
        return {
            "target": target, "value": value, "values": values,
            "unknown": unknown,
            "assumptions": assumptions,
            "note": ("A prediction is conditional on the supplied mechanisms. "
                     "It is not an observation."),
        }

    def counterfactual(self, target: str, outcome: str, value: Any) -> Counterfactual:
        if outcome not in self.nodes:
            return Counterfactual(outcome, status="unknown",
                                  reason="outcome node is not in the causal graph")
        result = self.intervene(target, value)
        if outcome in result["unknown"]:
            return Counterfactual(
                outcome, status="unknown",
                reason="no established mechanism connects the intervention to "
                       "this outcome",
                assumptions=result["assumptions"],
                evidence=["missing a mechanism or an observed causal edge"])
        return Counterfactual(
            outcome, predicted=result["values"].get(outcome),
            status="predicted",
            reason="prediction via explicit mechanisms; validate with an experiment",
            assumptions=result["assumptions"])

    def explanation(self, outcome: str) -> dict[str, Any]:
        """Return candidate causes, labeled by their evidence level."""
        rows = []
        for e in self.edges:
            if e.effect != outcome:
                continue
            rows.append({"cause": e.cause, "confidence": e.confidence,
                         "evidence": e.evidence})
        rows.sort(key=lambda r: CONFIDENCE.index(r["confidence"]), reverse=True)
        status = "established" if rows and all(
            r["confidence"] == "established" for r in rows) else (
            "observed" if any(r["confidence"] in ("observed", "established")
                              for r in rows) else "hypothesis")
        return {"outcome": outcome, "candidates": rows, "status": status,
                "note": "candidates are not proven causes until an intervention "
                        "or controlled experiment distinguishes them"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
            "mechanisms": sorted(self.mechanisms.keys()),
        }
