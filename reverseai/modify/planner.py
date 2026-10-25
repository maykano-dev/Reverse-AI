"""Explicit modification plans and blast-radius estimates.

The planner turns a strategy choice into an ordered, inspectable plan:

  investigate -> locate -> estimate impact -> implement -> verify

It also performs the "change this, preserve everything else" scoping pass:
which functions, sections, strings, and imports are likely involved, and how
much of the program is outside the edit. The plan is data, not execution; the
agent tools emit it as visible steps.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.models import AnalysisReport
from .strategy import StrategyChoice, is_ambiguous_goal

_STOP = {
    "a", "an", "the", "and", "or", "but", "to", "of", "in", "on", "for", "with",
    "it", "this", "that", "these", "those", "please", "can", "could", "would",
    "i", "we", "you", "me", "my", "our", "is", "are", "be", "make", "change",
    "want", "need", "so", "then", "from", "into", "as", "at", "by", "about",
    "should", "must", "will", "just", "only", "preserve", "keep", "everything",
    "else", "rest", "without", "affect", "affecting", "unchanged", "behavior",
    "behaviour", "new", "old", "currently", "instead", "please",
}
_SCOPE_WORDS = ("preserve", "everything else", "the rest", "without changing",
                "without affecting", "do not change", "don't change",
                "leave the rest", "keep everything", "only change", "only modify")
_RESOURCE_HINTS = ("rsrc", "rodata", "rdata", "cstring", "const", "data")


@dataclass
class PlanStep:
    id: str
    title: str
    detail: str
    tool: str = ""
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Component:
    kind: str          # function | section | string | import | export | entry
    name: str
    address: int | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BlastRadius:
    level: str = "unknown"   # low | medium | high | unknown
    functions: int = 0
    sections: int = 0
    strings: int = 0
    imports: int = 0
    note: str = ""
    unaffected: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModificationPlan:
    goal: str
    strategy: str
    mode: str
    recommended_mode: str
    confidence: float
    rationale: str
    steps: list[PlanStep] = field(default_factory=list)
    components: list[Component] = field(default_factory=list)
    blast_radius: BlastRadius = field(default_factory=BlastRadius)
    preserve_rest: bool = False
    needs_clarification: bool = False
    question: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "strategy": self.strategy,
            "mode": self.mode,
            "recommended_mode": self.recommended_mode,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "steps": [s.to_dict() for s in self.steps],
            "components": [c.to_dict() for c in self.components],
            "blast_radius": self.blast_radius.to_dict(),
            "preserve_rest": self.preserve_rest,
            "needs_clarification": self.needs_clarification,
            "question": self.question,
            "warnings": self.warnings,
        }


def _tokens(goal: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]+", (goal or "").lower())
            if t not in _STOP and len(t) >= 3]


def preserve_rest(goal: str) -> bool:
    low = (goal or "").lower()
    return any(phrase in low for phrase in _SCOPE_WORDS)


def _matches(name: str, words: list[str]) -> str | None:
    low = name.lower()
    for w in words:
        if w in low:
            return w
    return None


def identify_components(report: AnalysisReport, goal: str,
                        strategy: str) -> list[Component]:
    words = _tokens(goal)
    out: list[Component] = []
    seen: set[tuple[str, str]] = set()

    def add(c: Component) -> None:
        key = (c.kind, c.name)
        if key in seen:
            return
        seen.add(key)
        out.append(c)

    for f in report.functions:
        name = str(f.get("name", ""))
        hit = _matches(name, words)
        if hit:
            add(Component("function", name, f.get("address"),
                          f"name matches {hit!r}"))
    for s in report.sections:
        hit = _matches(s.name, words)
        if hit:
            add(Component("section", s.name, s.raw_offset,
                          f"section name matches {hit!r}"))
    for text in report.strings_sample:
        hit = _matches(text, words)
        if hit:
            add(Component("string", text[:160], None, f"embedded text matches {hit!r}"))
            if len([c for c in out if c.kind == "string"]) >= 6:
                break
    for lib, syms in report.imports.items():
        hit = _matches(lib, words)
        if hit:
            add(Component("import", lib, None, f"library name matches {hit!r}"))
        for sym in syms:
            hit = _matches(sym, words)
            if hit:
                add(Component("import", f"{lib}!{sym}", None,
                              f"imported symbol matches {hit!r}"))
                break
    for name in report.exports:
        hit = _matches(name, words)
        if hit:
            add(Component("export", name, None, f"exported symbol matches {hit!r}"))

    if strategy == "resource_edit":
        for s in report.sections:
            if any(h in s.name.lower() for h in _RESOURCE_HINTS):
                add(Component("section", s.name, s.raw_offset,
                              "resource-like section"))
    if strategy in ("byte_patch", "component_replace"):
        for s in report.sections:
            if s.name.lower() in (".text", "__text"):
                add(Component("section", s.name, s.raw_offset,
                              "executable code section"))
    if report.entry_point is not None:
        add(Component("entry", "entry point", report.entry_point,
                      "program entry point"))

    if not out:
        for s in report.sections[:4]:
            add(Component("section", s.name, s.raw_offset,
                          "fallback: relevant section"))
    return out[:12]


def estimate_blast_radius(report: AnalysisReport, components: list[Component],
                          strategy: str) -> BlastRadius:
    functions = sum(1 for c in components if c.kind == "function")
    sections = sum(1 for c in components if c.kind == "section")
    strings = sum(1 for c in components if c.kind == "string")
    imports = sum(1 for c in components if c.kind in ("import", "export"))
    stripped = not report.functions and not report.exports

    if strategy == "resource_edit":
        level = "low" if len(components) <= 3 else "medium"
        note = "A localized resource/string edit should not change control flow."
    elif strategy == "byte_patch":
        level = "high" if stripped or functions > 4 else "medium"
        note = ("A byte edit can be precise, but without symbols the affected "
                "logic is harder to bound." if stripped else
                "The edit targets a small number of located components.")
    elif strategy == "component_replace":
        level = "high"
        note = "Replacing a component changes an interface and its callers."
    elif strategy in ("rebuild", "reimplement"):
        level = "high"
        note = "A rebuild or reimplementation can change behavior far beyond the request."
    else:
        level = "unknown"
        note = "The strategy is not resolved yet."

    unaffected = (
        "All other functions, sections, and resources are outside the identified "
        "edit. The verification step will compare the untouched behavior with the "
        "original and block delivery on an unintended change.")
    return BlastRadius(level=level, functions=functions, sections=sections,
                       strings=strings, imports=imports, note=note,
                       unaffected=unaffected)


def _implementation_detail(strategy: str) -> tuple[str, str]:
    if strategy == "resource_edit":
        return ("Edit the embedded resource/string on a copy",
                "apply_byte_patch")
    if strategy == "byte_patch":
        return ("Apply the targeted byte patch on a copy", "apply_byte_patch")
    if strategy == "component_replace":
        return ("Replace the component through a structural edit", "add_section")
    if strategy == "rebuild":
        return ("Rebuild from the available sources/build recipe", "run_command")
    return ("Write the reimplementation and build it", "write_file")


def build_plan(report: AnalysisReport, goal: str, choice: StrategyChoice,
               *, has_sources: bool = False, has_cases: bool = False,
               has_preserve_cases: bool = False) -> ModificationPlan:
    components = identify_components(report, goal, choice.strategy)
    blast = estimate_blast_radius(report, components, choice.strategy)
    scoped = preserve_rest(goal)
    warnings: list[str] = list(choice.warnings)

    question = choice.question
    needs_clarification = choice.needs_clarification
    if not needs_clarification and is_ambiguous_goal(goal):
        needs_clarification = True
        question = ("What exactly should change, and what should the program do "
                    "differently? A concrete input and expected output is ideal.")
    if not needs_clarification and choice.strategy == "rebuild" and not has_sources:
        needs_clarification = True
        question = ("A rebuild needs the source tree or a reproducible build "
                    "recipe. Where are the sources, or should I use an in-place "
                    "edit instead?")

    if not has_cases:
        warnings.append("No behavioral expectation is declared yet; delivery will "
                        "be blocked until there is a passing test.")
    if scoped and not has_preserve_cases:
        warnings.append("This is a scoped request, but no regression inputs are "
                        "declared yet. Verification will need inputs that must stay unchanged.")

    locate = (", ".join(f"{c.kind}:{c.name}" for c in components[:5])
              or "no obvious named component; the change will need manual location")
    implement_title, implement_tool = _implementation_detail(choice.strategy)
    verify_detail = (
        "Run the declared behavioral expectations, then compare the untouched "
        "behavior with the original. Deliver only if the verify gate passes.")
    if scoped:
        verify_detail = (
            "Run the intended-change cases plus regression cases for the rest of "
            "the program. Any unintended difference blocks delivery.")

    steps = [
        PlanStep("investigate", "Investigate the target",
                 f"Read {report.fmt.value}, {report.arch.value} "
                 f"({report.bits}-bit), {len(report.sections)} sections, "
                 f"{len(report.functions)} functions, {report.string_count} strings.",
                 "analyze_binary", "done"),
        PlanStep("locate", "Locate the components that matter",
                 locate, "list_functions", "pending"),
        PlanStep("impact", "Estimate the blast radius",
                 f"{blast.level} risk. {blast.note} {blast.unaffected}",
                 "", "pending"),
        PlanStep("implement", implement_title, choice.rationale, implement_tool,
                 "pending"),
        PlanStep("verify", "Prove the change and preserve the rest",
                 verify_detail, "verify_modification", "pending"),
    ]
    return ModificationPlan(
        goal=goal, strategy=choice.strategy, mode=choice.mode,
        recommended_mode=choice.recommended_mode, confidence=choice.confidence,
        rationale=choice.rationale, steps=steps, components=components,
        blast_radius=blast, preserve_rest=scoped,
        needs_clarification=needs_clarification, question=question,
        warnings=warnings,
    )


def mark_step(plan: ModificationPlan, step_id: str, status: str) -> None:
    for s in plan.steps:
        if s.id == step_id:
            s.status = status
            return
