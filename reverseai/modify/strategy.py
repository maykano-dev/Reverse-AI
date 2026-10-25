"""Strategy selection for an autonomous modification.

Given a real ``AnalysisReport`` and the user's plain-language goal, score the
five modification strategies and prefer the smallest one that fits:

  resource_edit      change an embedded string/resource/asset
  byte_patch         targeted edit to logic or constants
  component_replace  swap a function/section, usually through LIEF
  rebuild            recompile from available sources/build files
  reimplement        reconstruct the behaviour in new code

The selector is deliberately conservative. A low-confidence or ambiguous request
returns ``needs_clarification`` with a question instead of guessing. Every choice
carries a rationale, evidence, alternatives, and warnings so the agent and the
user can see *why*.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from ..core.models import AnalysisReport, BinaryFormat

DIRECT = "direct"
RECONSTRUCTION = "reconstruction"
MODERNISATION = "modernisation"
MODES = (DIRECT, RECONSTRUCTION, MODERNISATION)

MODE_STRATEGIES = {
    DIRECT: ("resource_edit", "byte_patch", "component_replace"),
    RECONSTRUCTION: ("reimplement",),
    MODERNISATION: ("rebuild", "reimplement"),
}

STRATEGY_LABELS = {
    "resource_edit": "Edit the embedded resource",
    "byte_patch": "Patch the binary",
    "component_replace": "Replace a component",
    "rebuild": "Rebuild from source",
    "reimplement": "Reimplement the behaviour",
}

_STRATEGY_ORDER = ("resource_edit", "byte_patch", "component_replace",
                   "rebuild", "reimplement")

_RESOURCE_WORDS = {
    "string", "text", "message", "label", "caption", "title", "icon", "image",
    "asset", "resource", "version", "brand", "logo", "dialog", "menu", "url",
    "config", "embedded", "translation", "locale", "splash", "banner",
}
_BYTE_WORDS = {
    "patch", "byte", "jump", "branch", "condition", "check", "license", "trial",
    "activation", "bypass", "enable", "disable", "unlock", "compare", "return",
    "logic", "behaviour", "behavior", "flag", "constant", "magic", "nop",
}
_COMPONENT_WORDS = {
    "replace", "swap", "function", "routine", "section", "library", "import",
    "dependency", "component", "upgrade", "dll", "hook", "substitute",
}
_REBUILD_WORDS = {
    "rebuild", "recompile", "build", "source", "compile", "makefile", "cmake",
    "port", "dependency", "dependencies", "toolchain", "link",
}
_REIMPLEMENT_WORDS = {
    "reimplement", "rewrite", "recreate", "reconstruct", "reconstruction",
    "clone", "scratch", "alternative", "modernise", "modernize",
}
_MODERNISE_WORDS = {"modernise", "modernize", "new", "capability", "capabilities",
                    "upgrade", "port", "migrate", "replace"}

_STOP = {
    "a", "an", "the", "and", "or", "but", "to", "of", "in", "on", "for", "with",
    "it", "this", "that", "these", "those", "please", "can", "could", "would",
    "i", "we", "you", "me", "my", "our", "is", "are", "be", "make", "change",
    "want", "need", "so", "then", "from", "into", "as", "at", "by", "about",
    "should", "must", "will", "just",
}
_GENERIC = {
    "it", "this", "that", "thing", "stuff", "better", "good", "bad", "fix",
    "improve", "change", "modify", "update", "work", "something", "anything",
    "do", "help", "faster", "nice", "cool", "properly", "correctly",
}
_RESOURCE_SECTION_HINTS = ("rsrc", "rodata", "rdata", "cstring", "const",
                           "__text", "data")


@dataclass
class StrategyScore:
    strategy: str
    score: float
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyChoice:
    strategy: str
    mode: str
    recommended_mode: str
    confidence: float
    rationale: str
    evidence: list[str] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    needs_clarification: bool = False
    question: str = ""
    scores: dict[str, float] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return STRATEGY_LABELS.get(self.strategy, self.strategy)

    @property
    def confidence_label(self) -> str:
        if self.confidence >= 0.7:
            return "high"
        if self.confidence >= 0.45:
            return "medium"
        return "low"

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "label": self.label,
            "mode": self.mode,
            "recommended_mode": self.recommended_mode,
            "confidence": round(self.confidence, 3),
            "confidence_label": self.confidence_label,
            "rationale": self.rationale,
            "evidence": self.evidence,
            "alternatives": self.alternatives,
            "warnings": self.warnings,
            "needs_clarification": self.needs_clarification,
            "question": self.question,
            "scores": {k: round(v, 2) for k, v in self.scores.items()},
        }


def _lief_available() -> bool:
    try:
        return importlib.util.find_spec("lief") is not None
    except (ImportError, ValueError):
        return False


def _tokens(goal: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9_]+", (goal or "").lower())
            if t not in _STOP]


def is_ambiguous_goal(goal: str) -> bool:
    """True when the request has no concrete object or intended behaviour."""
    text = (goal or "").strip().lower()
    if not text:
        return True
    words = _tokens(text)
    if not words:
        return True
    if len(words) <= 3 and all(w in _GENERIC for w in words):
        return True
    if text in {"make it better", "fix it", "change it", "improve it",
                "make it faster", "do something", "help me"}:
        return True
    if all(w in _GENERIC for w in words):
        return True
    # "change this, preserve everything else" has no object to change.
    if len(words) <= 5 and all(w in _GENERIC or w in {"preserve", "everything",
                                                      "else", "rest", "only"}
                               for w in words):
        return True
    return False


def _contains_any(goal: str, words: set[str]) -> list[str]:
    low = (goal or "").lower()
    return sorted(w for w in words if w in low)


def _section_names(report: AnalysisReport) -> list[str]:
    return [s.name.lower() for s in report.sections]


def _function_names(report: AnalysisReport) -> list[str]:
    return [str(f.get("name", "")).lower() for f in report.functions]


def _is_stripped(report: AnalysisReport) -> bool:
    return not report.functions and not report.exports


def _evidence_lines(report: AnalysisReport) -> list[str]:
    lines = [
        f"format={report.fmt.value}, arch={report.arch.value}, bits={report.bits}",
        f"sections={len(report.sections)}, functions={len(report.functions)}, "
        f"strings={report.string_count}, imports={sum(len(v) for v in report.imports.values())}, "
        f"exports={len(report.exports)}",
    ]
    resource_sections = [s.name for s in report.sections
                         if any(h in s.name.lower() for h in _RESOURCE_SECTION_HINTS)]
    if resource_sections:
        lines.append("resource-like sections: " + ", ".join(resource_sections[:8]))
    if _is_stripped(report):
        lines.append("symbols are stripped or unavailable")
    return lines


def _score(report: AnalysisReport, goal: str, strategy: str,
           has_sources: bool, lief: bool) -> StrategyScore:
    low = (goal or "").lower()
    sections = _section_names(report)
    funcs = _function_names(report)
    strings = [s.lower() for s in report.strings_sample]
    score = 0.0
    reasons: list[str] = []
    blockers: list[str] = []

    if strategy == "resource_edit":
        hits = _contains_any(low, _RESOURCE_WORDS)
        score += min(6.0, 2.0 * len(hits))
        if hits:
            reasons.append("the request names resource-like content: " + ", ".join(hits))
        resource_sections = [s for s in sections
                             if any(h in s for h in _RESOURCE_SECTION_HINTS)]
        if resource_sections:
            score += 2.0
            reasons.append("the file has resource-like sections: "
                           + ", ".join(resource_sections[:5]))
        if report.fmt is BinaryFormat.PE and any("rsrc" in s for s in sections):
            score += 2.0
            reasons.append("the PE has a .rsrc resource directory")
        if strings and hits and any(h in " ".join(strings[:200]) for h in hits):
            score += 1.0
            reasons.append("matching text appears in the extracted strings")
        if report.fmt is BinaryFormat.UNKNOWN:
            blockers.append("the container format is unknown")

    elif strategy == "byte_patch":
        hits = _contains_any(low, _BYTE_WORDS)
        score += min(6.0, 2.0 * len(hits))
        if hits:
            reasons.append("the request names logic/byte-level intent: " + ", ".join(hits))
        if funcs:
            score += 2.0
            reasons.append(f"{len(funcs)} named functions are available to locate the change")
        if report.entry_point is not None:
            score += 1.0
            reasons.append("an entry point is available")
        if any(".text" in s for s in sections):
            score += 1.0
            reasons.append("an executable .text section is present")
        if report.imports or report.exports:
            score += 1.0
            reasons.append("imports/exports give extra anchors")
        if _is_stripped(report):
            score -= 1.0
            reasons.append("symbols are stripped, so locating the site is harder")

    elif strategy == "component_replace":
        hits = _contains_any(low, _COMPONENT_WORDS)
        score += min(6.0, 2.0 * len(hits))
        if hits:
            reasons.append("the request asks for a component-level replacement: "
                           + ", ".join(hits))
        if funcs:
            score += 1.0
            reasons.append("named functions can be targets")
        if sections:
            score += 1.0
            reasons.append("section boundaries are available")
        if lief:
            score += 2.0
            reasons.append("LIEF is installed for structural edits")
        else:
            score -= 1.5
            blockers.append("LIEF is not installed; structural replacement is unavailable")
        if report.fmt in (BinaryFormat.PE, BinaryFormat.ELF):
            score += 1.0
            reasons.append(f"{report.fmt.value.upper()} is supported by the structural editor")

    elif strategy == "rebuild":
        hits = _contains_any(low, _REBUILD_WORDS)
        score += min(6.0, 3.0 * len(hits))
        if hits:
            reasons.append("the request asks for a build-level change: " + ", ".join(hits))
        if has_sources:
            score += 4.0
            reasons.append("source or build files are available")
        else:
            score -= 2.0
            blockers.append("no source tree or build recipe is available")
        if report.fmt is BinaryFormat.UNKNOWN:
            blockers.append("the target format is unknown")

    elif strategy == "reimplement":
        hits = _contains_any(low, _REIMPLEMENT_WORDS)
        score += min(6.0, 3.0 * len(hits))
        if hits:
            reasons.append("the request asks for reconstruction: " + ", ".join(hits))
        if funcs or sections or strings:
            score += 1.0
            reasons.append("the analysis provides behaviour to reconstruct")
        if report.fmt is not BinaryFormat.UNKNOWN:
            score += 1.0
            reasons.append("the format is identified, so the reconstructed behaviour has a target")
        if _is_stripped(report):
            reasons.append("symbols are stripped; reconstruction will rely on observed behaviour")

    return StrategyScore(strategy, max(0.0, score), reasons, blockers)


def _recommended_mode(strategy: str, goal: str) -> str:
    if strategy in MODE_STRATEGIES[DIRECT]:
        return DIRECT
    if strategy == "rebuild":
        return MODERNISATION
    if _contains_any(goal, _MODERNISE_WORDS):
        return MODERNISATION
    return RECONSTRUCTION


def _question_for(report: AnalysisReport, goal: str, scores: dict[str, float]) -> str:
    if report.fmt is BinaryFormat.UNKNOWN:
        return ("I could not identify the container format, so I cannot choose a "
                "safe modification strategy. What kind of file is this?")
    if is_ambiguous_goal(goal):
        return ("What exactly should change, and what should the program do "
                "differently? A concrete input and expected output is ideal.")
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if len(ordered) > 1 and ordered[0][1] - ordered[1][1] <= 0.75:
        return (f"I can see at least two plausible approaches ({ordered[0][0]} and "
                f"{ordered[1][0]}). Which outcome matters most: a small in-place "
                "edit, or a broader rebuild/reimplementation?")
    return ("The evidence is too thin to choose confidently. Can you describe the "
            "current behaviour and the exact new behaviour you want?")


def choose_strategy(report: AnalysisReport, goal: str, mode: str | None = None,
                    has_sources: bool = False,
                    lief_available: bool | None = None) -> StrategyChoice:
    """Score the strategies and return a choice, rationale, and confidence."""
    lief = _lief_available() if lief_available is None else bool(lief_available)
    mode = (mode or "").strip().lower() or None
    warnings: list[str] = []
    if mode is not None and mode not in MODES:
        return StrategyChoice(
            strategy="byte_patch", mode=DIRECT, recommended_mode=DIRECT,
            confidence=0.1,
            rationale="The requested mode is not recognized.",
            warnings=[f"unknown mode: {mode!r}; expected one of {', '.join(MODES)}"],
            needs_clarification=True,
            question="Which mode should I use: Direct, Reconstruction, or Modernisation?",
        )

    scores = {
        name: _score(report, goal, name, has_sources, lief)
        for name in _STRATEGY_ORDER
    }
    raw = {k: v.score for k, v in scores.items()}
    overall = max(_STRATEGY_ORDER, key=lambda k: raw[k])
    recommended_mode = _recommended_mode(overall, goal)

    allowed = MODE_STRATEGIES[mode] if mode else _STRATEGY_ORDER
    selected = max(allowed, key=lambda k: raw.get(k, 0.0))
    selected_score = raw.get(selected, 0.0)
    second = sorted((raw[k] for k in allowed), reverse=True)
    second_score = second[1] if len(second) > 1 else 0.0

    if mode and selected != overall:
        warnings.append(
            f"You chose {mode.title()}; the strongest overall fit was {overall}, "
            f"but it is outside that mode.")
    if selected == "component_replace" and not lief:
        warnings.append("LIEF is not installed; component replacement may be unavailable.")
    if selected == "rebuild" and not has_sources:
        warnings.append("No source/build files were found; a rebuild cannot run yet.")
    if _is_stripped(report):
        warnings.append("Symbols are stripped; locating the exact change will need more evidence.")
    if report.fmt is BinaryFormat.UNKNOWN:
        warnings.append("The format is unknown; analysis is limited.")

    evidence = _evidence_lines(report)
    reasons = scores[selected].reasons or ["no strong signal was found in the request"]
    confidence = min(0.95, max(0.08, selected_score / 10.0))
    if mode and selected != overall:
        confidence = min(confidence, 0.65)
    if _is_stripped(report):
        confidence = min(confidence, 0.7)

    needs_clarification = False
    question = ""
    if is_ambiguous_goal(goal):
        needs_clarification = True
        question = _question_for(report, goal, raw)
    elif report.fmt is BinaryFormat.UNKNOWN:
        needs_clarification = True
        question = _question_for(report, goal, raw)
    elif selected_score < 4.0:
        needs_clarification = True
        question = _question_for(report, goal, raw)
    elif selected_score - second_score <= 0.75 and selected_score < 7.0:
        needs_clarification = True
        question = _question_for(report, goal, raw)
    elif selected == "rebuild" and not has_sources:
        needs_clarification = True
        question = ("A rebuild needs the source tree or a reproducible build recipe. "
                    "Where are the sources, or should I use an in-place edit instead?")
    elif selected == "reimplement" and not _contains_any(goal, _REIMPLEMENT_WORDS):
        needs_clarification = True
        question = ("Reimplementation is a larger change. Which language/runtime should "
                    "the new implementation use, and what behaviour must it preserve?")

    label = STRATEGY_LABELS[selected]
    mode_line = f"Recommended mode: {mode or recommended_mode.title()}."
    if mode:
        mode_line = f"Using your requested mode: {mode.title()}."
    rationale = (
        f"I recommend {label.lower()} because " + "; ".join(reasons) + ". "
        f"{mode_line} "
        f"Confidence is {confidence:.0%}.")
    if warnings:
        rationale += " " + " ".join(warnings)

    alternatives = [
        {"strategy": k, "score": round(raw[k], 2),
         "note": "; ".join(scores[k].reasons[:2]) or "weak fit"}
        for k in _STRATEGY_ORDER if k != selected
    ]
    alternatives.sort(key=lambda x: x["score"], reverse=True)

    return StrategyChoice(
        strategy=selected,
        mode=mode or recommended_mode,
        recommended_mode=recommended_mode,
        confidence=confidence,
        rationale=rationale,
        evidence=evidence,
        alternatives=alternatives,
        warnings=warnings,
        needs_clarification=needs_clarification,
        question=question,
        scores=raw,
    )
