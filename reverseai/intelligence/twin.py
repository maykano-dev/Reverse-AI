"""Digital twins and provisional simulation environments.

A twin is not the real system. It is a computational sketch of the components,
contracts, and workflows we have evidence for. The output of a simulation is a
prediction with a scope, never a deployment guarantee.

The hybrid plan is the honest part: simulate what is modeled, test what is not,
and name the parts that remain unknown.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .world import WorldModel


@dataclass
class Contract:
    component: str
    requires: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TwinChange:
    node_id: str
    description: str
    removes: list[str] = field(default_factory=list)
    adds: list[str] = field(default_factory=list)
    modifies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TwinSimulation:
    change: TwinChange
    affected: list[dict[str, Any]] = field(default_factory=list)
    predicted_failures: list[dict[str, Any]] = field(default_factory=list)
    unverified: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = "hypothesis"
    summary: str = ""
    hybrid_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "change": self.change.to_dict(),
            "affected": self.affected,
            "predicted_failures": self.predicted_failures,
            "unverified": self.unverified,
            "confidence": self.confidence,
            "summary": self.summary,
            "hybrid_plan": self.hybrid_plan,
        }


@dataclass
class SimulatedEnvironment:
    id: str
    kind: str
    spec: dict[str, Any]
    assumptions: list[str] = field(default_factory=list)
    omissions: list[str] = field(default_factory=list)
    validated_against: list[str] = field(default_factory=list)
    status: str = "provisional"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DigitalTwin:
    def __init__(self, world: WorldModel) -> None:
        self.world = world
        self.contracts: dict[str, Contract] = {}

    def add_contract(self, contract: Contract) -> None:
        self.contracts[contract.component] = contract

    def _affected(self, node_id: str) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out = []
        for n in [self.world.get(node_id)] + self.world.descendants(node_id) + \
                self.world.ancestors(node_id):
            if n is None or n.id in seen:
                continue
            seen.add(n.id)
            out.append({"id": n.id, "kind": n.kind, "name": n.name,
                        "confidence": n.provenance.confidence})
        return out

    def simulate(self, change: TwinChange) -> TwinSimulation:
        if change.node_id not in self.world.nodes:
            raise ValueError("twin change targets an unknown node")
        affected = self._affected(change.node_id)
        failures = []
        unverified = []
        for row in affected:
            contract = self.contracts.get(row["id"])
            if contract is None:
                unverified.append({**row, "why": "no contract or runtime observation"})
                continue
            broken = []
            for removed in change.removes:
                if removed in contract.requires or removed in contract.provides:
                    broken.append(f"removes contract item {removed!r}")
            for invariant in contract.invariants:
                if invariant in change.modifies:
                    broken.append(f"modifies invariant {invariant!r}")
            if broken:
                failures.append({
                    **row, "why": broken,
                    "confidence": "observed" if contract.evidence else "hypothesis",
                })
        modeled = [r for r in affected if self.contracts.get(r["id"])]
        confidence = "observed" if modeled and not unverified else "hypothesis"
        hybrid = {
            "simulate": [r["name"] for r in modeled],
            "live_test": [r["name"] for r in unverified],
            "unknown": [r["name"] for r in affected
                        if r["confidence"] in ("unknown", "hypothesis")
                        and r["id"] not in {u["id"] for u in unverified}],
            "rule": ("A contract is a model. Predictions must be confirmed by a "
                     "sandbox test before any change is accepted."),
        }
        summary = (f"{len(affected)} affected component(s), "
                   f"{len(failures)} predicted failure(s), "
                   f"{len(unverified)} unmodeled component(s).")
        return TwinSimulation(change, affected, failures, unverified,
                              confidence, summary, hybrid)

    def summary(self) -> dict[str, Any]:
        return {
            "nodes": len(self.world.nodes),
            "contracts": len(self.contracts),
            "modeled": len(self.contracts),
            "unmodeled": len(self.world.nodes) - len(self.contracts),
            "note": "a twin is only as good as its contracts and observations",
        }


class SimulationFactory:
    """Generate a provisional mock environment from a world model.

    The factory does not claim the mock is equivalent to production. It records
    the assumptions, the omissions, and what it has been validated against.
    """

    def from_world(self, world: WorldModel, kind: str = "service") -> SimulatedEnvironment:
        nodes = list(world.nodes.values())
        deps = [n for n in nodes if n.kind in ("dependency", "service", "api")]
        data = [n for n in nodes if n.kind in ("dataset", "database", "file")]
        spec = {
            "kind": kind,
            "endpoints": [n.name for n in deps][:30],
            "data_sources": [n.name for n in data][:30],
            "components": [n.name for n in nodes
                           if n.kind in ("component", "module", "service")][:50],
        }
        assumptions = [
            "the mock accepts the same shape of inputs as the modeled components",
            "no production credentials or data are present",
            "timing and resource limits are approximate",
        ]
        omissions = [
            "unmodeled side effects",
            "real network latency and partial failure",
            "authorization and tenancy boundaries not represented in the model",
        ]
        return SimulatedEnvironment(
            f"sim_{uuid.uuid4().hex[:10]}", kind, spec,
            assumptions, omissions,
            validated_against=[], status="provisional")
