"""Engineering intelligence: world models, discovery, experiments, and proof.

The modules here are deliberately data-first. They do not execute target code;
they build explicit structures the agent can inspect, test, and invalidate.
Anything that needs execution is handed to ``reverseai.sandbox`` by the caller.
"""

from .causal import CausalGraph, Counterfactual
from .design import AlgorithmOptimizer, ArchitectureSearch, Candidate, Objective
from .discovery import DiscoveryEngine, Opportunity
from .product import BehaviorContract, ProductSpec, build_product_plan, parse_spec
from .science import ExperimentEngine, Hypothesis, RealityEngine
from .twin import DigitalTwin, SimulationFactory
from .world import (
    Edge,
    EngineeringRecord,
    MemoryFabric,
    Node,
    Provenance,
    WorldModel,
    world_from_analysis,
)

__all__ = [
    "Provenance", "Node", "Edge", "EngineeringRecord", "WorldModel",
    "MemoryFabric", "world_from_analysis", "DiscoveryEngine", "Opportunity",
    "ExperimentEngine", "Hypothesis", "RealityEngine", "CausalGraph",
    "Counterfactual", "DigitalTwin", "SimulationFactory", "ArchitectureSearch",
    "Candidate", "Objective", "AlgorithmOptimizer", "ProductSpec",
    "BehaviorContract", "parse_spec", "build_product_plan",
]
