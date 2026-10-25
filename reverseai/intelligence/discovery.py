"""Autonomous discovery: find questions worth asking.

This is not a random "insight generator." Every opportunity points to a concrete
observation (a symbol, string, section, import, or missing test) and carries a
falsifiable next step. The engine separates:

  observed       what the parser actually found
  hypothesis     a plausible explanation that has not been tested
  opportunity    an action with an expected benefit and a cost/risk estimate

An opportunity is never a delivered change. It is a proposal, and anything that
would modify a system is marked as requiring approval.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .science import Hypothesis
from .world import WorldModel

CATEGORIES = (
    "hidden_feature", "undocumented_api", "performance", "architecture",
    "dependency", "missing_tests", "security", "unlockable_capability",
    "dead_code", "data_quality",
)

_HIDDEN_WORDS = ("debug", "admin", "internal", "hidden", "secret", "backdoor",
                 "test_mode", "developer", "diagnostic", "unsafe", "override")
_UNLOCK_WORDS = ("enable", "disable", "feature", "toggle", "unlock", "premium",
                 "trial", "license", "flag", "config", "experimental")
_NET_WORDS = ("http://", "https://", "api.", "/api/", "token", "bearer",
              "upload", "webhook", "socket")
_DANGEROUS_IMPORTS = ("system", "popen", "exec", "eval", "dlopen", "ptrace",
                      "fork", "setuid", "chmod", "unlink", "remove")


@dataclass
class Opportunity:
    id: str
    category: str
    title: str
    description: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = "hypothesis"      # observed | hypothesis
    impact: int = 2                     # 1..5
    effort: int = 3                     # 1..5
    risk: int = 2                       # 1..5
    benefit: int = 3                    # 1..5
    score: float = 0.0
    proposed_action: str = ""
    requires_approval: bool = False
    hypothesis: str = ""
    status: str = "proposed"            # proposed | investigating | accepted | rejected

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _id() -> str:
    return f"opp_{uuid.uuid4().hex[:12]}"


def _score(impact: int, benefit: int, confidence: str, effort: int, risk: int) -> float:
    weight = 1.0 if confidence == "observed" else 0.55
    raw = (max(1, impact) * max(1, benefit) * weight) / (max(1, effort) * max(1, risk))
    return round(min(10.0, raw * 2.0), 3)


def _hits(values: Iterable[str], words: tuple[str, ...], limit: int = 8) -> list[str]:
    out = []
    for value in values:
        low = str(value).lower()
        if any(w in low for w in words):
            out.append(str(value)[:160])
            if len(out) >= limit:
                break
    return out


class DiscoveryEngine:
    def __init__(self, world: WorldModel | None = None,
                 memory: Any = None) -> None:
        self.world = world or WorldModel()
        self.memory = memory
        self.opportunities: list[Opportunity] = []

    def _add(self, category: str, title: str, description: str, *,
             evidence: list[dict[str, Any]], confidence: str = "hypothesis",
             impact: int = 2, effort: int = 3, risk: int = 2, benefit: int = 3,
             action: str = "", approval: bool = False,
             hypothesis: str = "") -> Opportunity:
        opp = Opportunity(
            _id(), category, title[:240], description[:2000],
            evidence[:12], confidence, impact, effort, risk, benefit,
            _score(impact, benefit, confidence, effort, risk),
            action[:500], approval, hypothesis[:1000])
        self.opportunities.append(opp)
        return opp

    def discover(self, report, *, corpus_present: bool = False,
                 tests_present: bool = False) -> list[Opportunity]:
        """Analyze a real report and emit ranked, evidence-backed opportunities."""
        functions = [str(f.get("name") or "") for f in report.functions or []]
        strings = list(report.strings_sample or [])
        exports = list(report.exports or [])
        imports = {k: list(v) for k, v in (report.imports or {}).items()}
        imported_syms = [s for syms in imports.values() for s in syms]
        dynamic = list(report.dynamic_symbols or [])
        sections = list(report.sections or [])
        high_entropy = [s.name for s in sections if s.entropy >= 7.0]

        hidden = _hits(functions + strings, _HIDDEN_WORDS)
        if hidden:
            self._add(
                "hidden_feature", "Possible hidden or diagnostic functionality",
                "Names or strings associated with debug/admin/override behavior "
                "appear in the artifact. This is a lead, not proof that the path "
                "is reachable or undocumented.",
                evidence=[{"kind": "symbol_or_string", "value": h} for h in hidden],
                confidence="observed", impact=4, effort=3, risk=2, benefit=4,
                action="Locate the entry points and test their runtime behavior in the sandbox.",
                approval=True,
                hypothesis="These debug/admin paths are reachable without special inputs.")

        unlock = _hits(functions + strings, _UNLOCK_WORDS)
        if unlock:
            self._add(
                "unlockable_capability", "Possible feature gate or dormant capability",
                "Feature/flag/license-like strings may represent a gate. The "
                "correct next step is to observe the gate, not to assume that "
                "changing it is safe or authorized.",
                evidence=[{"kind": "symbol_or_string", "value": u} for u in unlock],
                confidence="hypothesis", impact=4, effort=4, risk=4, benefit=4,
                action="Trace the gate and prove the intended behavior with a scoped test.",
                approval=True,
                hypothesis="A feature gate controls a capability that is otherwise present.")

        net = _hits(strings + imported_syms, _NET_WORDS)
        if net:
            self._add(
                "undocumented_api", "Possible undocumented network or file interface",
                "Network/API/token-like strings and symbols appeared. They may be "
                "dead resources, a real interface, or a test fixture; the evidence "
                "does not distinguish those yet.",
                evidence=[{"kind": "string_or_symbol", "value": n} for n in net],
                confidence="observed", impact=3, effort=3, risk=3, benefit=3,
                action="Enumerate the endpoints and test them only against an authorized instance.",
                approval=True,
                hypothesis="At least one discovered endpoint is live and reachable.")

        if high_entropy:
            self._add(
                "architecture", "High-entropy sections may hide packing or encryption",
                "Entropy above 7.0 is a signal, not a diagnosis. It can be a "
                "compressed asset, a cryptographic blob, or packed code.",
                evidence=[{"kind": "section", "value": s} for s in high_entropy[:6]],
                confidence="observed", impact=4, effort=4, risk=3, benefit=3,
                action="Test the unpacking hypothesis against runtime imports and memory.",
                approval=False,
                hypothesis="The high-entropy section is packed executable code.")

        dep_count = len(imports)
        sym_count = len(imported_syms)
        if dep_count >= 12 or sym_count >= 150:
            self._add(
                "dependency", "Large dependency surface",
                f"{dep_count} imported libraries and {sym_count} imported symbols "
                "increase the attack and maintenance surface. This is an observed "
                "count, not a claim that every dependency is unnecessary.",
                evidence=[{"kind": "imports", "libraries": dep_count,
                           "symbols": sym_count}],
                confidence="observed", impact=3, effort=3, risk=2, benefit=3,
                action="Map which dependencies are actually used on the reachable paths.",
                hypothesis="A meaningful fraction of these imports is unused or replaceable.")

        if functions and not exports:
            self._add(
                "undocumented_api", "Internal functions without a public export surface",
                f"{len(functions)} named functions were recovered but no exports "
                "were listed. Some may be internal entry points or an undocumented "
                "interface. Static names do not prove callability.",
                evidence=[{"kind": "functions", "count": len(functions)}],
                confidence="observed", impact=3, effort=3, risk=2, benefit=3,
                action="Cross-reference call sites and test one candidate in isolation.",
                hypothesis="At least one internal function is a useful, callable interface.")

        dangerous = _hits(imported_syms + dynamic, _DANGEROUS_IMPORTS)
        if dangerous:
            self._add(
                "security", "Sharp-edged imported operations",
                "The binary imports process, file, or permission primitives that "
                "deserve a threat-model review. Their presence is not a vulnerability.",
                evidence=[{"kind": "import", "value": d} for d in dangerous],
                confidence="observed", impact=4, effort=3, risk=3, benefit=4,
                action="Review the call sites and test the boundary with malformed inputs.",
                approval=False,
                hypothesis="One of these call sites accepts attacker-controlled input.")

        if not report.functions:
            self._add(
                "architecture", "Symbols are stripped or unavailable",
                "Function-level reasoning will depend on disassembly, control-flow "
                "recovery, and runtime observation. Name-based conclusions are weak.",
                evidence=[{"kind": "analysis", "functions": 0}],
                confidence="observed", impact=3, effort=4, risk=2, benefit=3,
                action="Run the control-flow graph and a behavioral corpus before changing anything.",
                hypothesis="The stripped binary still has recoverable function boundaries.")

        if not corpus_present:
            self._add(
                "missing_tests", "No durable behavioral corpus",
                "There is no captured original behavior, so a later change cannot "
                "prove that unrelated behavior was preserved.",
                evidence=[{"kind": "corpus", "present": False}],
                confidence="observed", impact=4, effort=2, risk=1, benefit=4,
                action="Capture a corpus of safe inputs, including negative controls.",
                approval=False,
                hypothesis="Captured default behavior is stable enough to use as a regression baseline.")

        if not tests_present:
            self._add(
                "missing_tests", "No declared acceptance tests",
                "The system can analyze and modify the target, but no acceptance "
                "criteria are attached to the requested outcome.",
                evidence=[{"kind": "tests", "present": False}],
                confidence="observed", impact=4, effort=2, risk=1, benefit=4,
                action="Write at least one intended-change case and one preserved-behavior case.",
                approval=False,
                hypothesis="The intended behavior can be expressed as an observable input/output pair.")

        if report.entry_point is not None and not high_entropy:
            self._add(
                "performance", "Entry point is a profiling candidate",
                "No performance claim is made from static data. This is a profile "
                "target: measure first, then optimize with an equivalence check.",
                evidence=[{"kind": "entry_point", "value": report.entry_point}],
                confidence="hypothesis", impact=2, effort=3, risk=2, benefit=2,
                action="Benchmark representative inputs before and after any change.",
                hypothesis="A measurable hot path exists near the entry point.")

        if self.world.nodes:
            weak = self.world.weak_components()
            if weak:
                self._add(
                    "architecture", "Components with only hypothesis-level evidence",
                    f"{len(weak)} components in the world model are not verified. "
                    "The model should not be used as if those links were facts.",
                    evidence=[{"kind": "world_model", "weak": len(weak)}],
                    confidence="observed", impact=3, effort=2, risk=2, benefit=3,
                    action="Attach observations or experiments to the weak components.",
                    hypothesis="Some weak links are the actual cause of the observed behavior.")

        self.opportunities.sort(key=lambda o: (o.score, o.impact), reverse=True)
        return list(self.opportunities)

    def hypotheses(self) -> list[Hypothesis]:
        out = []
        for opp in self.opportunities:
            if opp.hypothesis:
                out.append(Hypothesis(
                    f"hyp_{opp.id[-8:]}", opp.hypothesis,
                    predicts={"changes_behavior": True},
                    scope=opp.title))
        return out

    def mission(self, *, max_steps: int = 6,
                max_effort: int = 15) -> dict[str, Any]:
        """Order investigations by score and stop when effort is exhausted."""
        chosen = []
        spent = 0
        for opp in sorted(self.opportunities, key=lambda o: o.score, reverse=True):
            if spent + opp.effort > max_effort or len(chosen) >= max_steps:
                continue
            chosen.append(opp.to_dict())
            spent += opp.effort
        return {
            "opportunities": chosen,
            "steps": len(chosen),
            "effort_budget": max_effort,
            "effort_spent": spent,
            "stop_condition": ("stop when the remaining opportunities have "
                               "lower expected value than the cost of another test"),
            "note": "This is a plan, not permission to modify the system.",
        }

    def summary(self) -> dict[str, Any]:
        by_cat: dict[str, int] = {}
        for o in self.opportunities:
            by_cat[o.category] = by_cat.get(o.category, 0) + 1
        return {
            "total": len(self.opportunities),
            "categories": by_cat,
            "top_score": round(max((o.score for o in self.opportunities), default=0), 3),
            "requires_approval": sum(1 for o in self.opportunities if o.requires_approval),
        }
