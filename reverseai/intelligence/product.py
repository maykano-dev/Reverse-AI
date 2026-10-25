"""Specification-to-product and software-from-behaviour.

Two related ideas:

1. Turn an intent into requirements, acceptance criteria, constraints, a threat
   model, and a phased plan.
2. When only behaviour is available, build an observable contract and report
   exactly what was matched, what was not, and what remains unknown.

Neither module claims to recover internal source code from observations.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

_STOP = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with",
         "it", "this", "that", "we", "you", "i", "should", "must", "would"}
_LANGS = {
    ".py": "Python", ".rs": "Rust", ".go": "Go", ".c": "C", ".h": "C/C++",
    ".cc": "C++", ".cpp": "C++", ".java": "Java", ".kt": "Kotlin",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript",
    ".jsx": "JavaScript", ".cs": "C#", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".m": "Objective-C", ".scala": "Scala", ".sh": "Shell",
}
_BUILD = {
    "pyproject.toml": "Python packaging", "setup.py": "Python packaging",
    "Cargo.toml": "Cargo", "go.mod": "Go modules", "package.json": "npm",
    "CMakeLists.txt": "CMake", "Makefile": "Make", "meson.build": "Meson",
    "pom.xml": "Maven", "build.gradle": "Gradle",
}


@dataclass
class Requirement:
    id: str
    text: str
    priority: str = "must"       # must | should | could
    acceptance: list[str] = field(default_factory=list)
    status: str = "open"         # open | implemented | verified | dropped
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProductSpec:
    goal: str
    requirements: list[Requirement] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    non_goals: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    threat_model: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    version: int = 1

    def add_requirement(self, text: str, *, priority: str = "must",
                        acceptance: list[str] | None = None) -> Requirement:
        req = Requirement(f"req_{uuid.uuid4().hex[:10]}", text[:2000],
                          priority, list(acceptance or []))
        self.requirements.append(req)
        self.version += 1
        return req

    def change_requirement(self, req_id: str, *, text: str | None = None,
                           priority: str | None = None,
                           status: str | None = None) -> Requirement:
        for req in self.requirements:
            if req.id != req_id:
                continue
            if text is not None:
                req.text = text[:2000]
            if priority is not None:
                req.priority = priority
            if status is not None:
                req.status = status
            self.version += 1
            self.decisions.append({
                "kind": "requirement_change", "requirement": req_id,
                "text": req.text, "status": req.status,
            })
            return req
        raise KeyError("requirement not found")

    def gaps(self) -> list[dict[str, Any]]:
        return [{"id": r.id, "text": r.text,
                 "why": "no acceptance criteria" if not r.acceptance else
                        "not verified"}
                for r in self.requirements
                if r.status != "verified"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "requirements": [r.to_dict() for r in self.requirements],
            "constraints": self.constraints, "non_goals": self.non_goals,
            "platforms": self.platforms, "threat_model": self.threat_model,
            "assumptions": self.assumptions, "decisions": self.decisions,
            "version": self.version,
        }


def parse_spec(goal: str, detail: str = "") -> ProductSpec:
    text = f"{goal}. {detail}".strip()
    spec = ProductSpec(goal.strip()[:2000])
    sentences = [s.strip() for s in re.split(r"[.\n;]+", text) if s.strip()]
    for sentence in sentences[:40]:
        low = sentence.lower()
        if any(w in low for w in ("must", "shall", "needs to", "should", "build",
                                  "support", "allow", "secure", "works on")):
            spec.add_requirement(sentence)
        if any(w in low for w in ("without", "no more than", "within", "cannot",
                                  "must not", "constraint", "budget")):
            spec.constraints.append(sentence)
        if any(w in low for w in ("out of scope", "non-goal", "not required",
                                  "won't", "will not")):
            spec.non_goals.append(sentence)
    for platform in ("linux", "windows", "macos", "android", "ios", "web",
                     "docker", "kubernetes", "embedded"):
        if platform in text.lower():
            spec.platforms.append(platform)
    spec.threat_model = [
        "untrusted input at every boundary",
        "least privilege for services and credentials",
        "no secrets in source, logs, or artifacts",
    ]
    if not spec.requirements:
        spec.assumptions.append(
            "the goal did not contain an explicit testable requirement; "
            "a human must confirm the acceptance criteria")
    return spec


def build_product_plan(spec: ProductSpec) -> dict[str, Any]:
    steps = [
        {"id": "requirements", "title": "Freeze requirements and acceptance criteria",
         "detail": f"{len(spec.requirements)} requirement(s); "
                   f"{len(spec.gaps())} gap(s) remain."},
        {"id": "architecture", "title": "Choose an architecture and threat model",
         "detail": "Record trade-offs; do not pick a stack by habit."},
        {"id": "interfaces", "title": "Design interfaces and data contracts",
         "detail": "Inputs, outputs, errors, permissions, and compatibility."},
        {"id": "implementation", "title": "Implement in small verified slices",
         "detail": "Each slice needs a test and a rollback point."},
        {"id": "verification", "title": "Independent verification",
         "detail": "Acceptance tests, negative tests, security review, and a "
                   "prohibited-change check."},
        {"id": "delivery", "title": "Package, document, deploy, and roll back",
         "detail": "Reproduction instructions and a tested rollback plan."},
    ]
    return {
        "goal": spec.goal,
        "spec": spec.to_dict(),
        "steps": steps,
        "note": "This is a plan. It is not a claim that the software exists.",
    }


@dataclass
class BehaviorCase:
    name: str
    inputs: dict[str, Any] = field(default_factory=dict)
    expected: Any = None
    observed: Any = None
    matched: bool | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BehaviorContract:
    source: str = ""
    cases: list[BehaviorCase] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    scope: str = ""
    confidence: str = "hypothesis"

    def add(self, name: str, inputs: dict[str, Any], expected: Any) -> BehaviorCase:
        c = BehaviorCase(name, dict(inputs), expected)
        self.cases.append(c)
        return c

    def evaluate(self, runner: Callable[[dict[str, Any]], Any]) -> dict[str, Any]:
        matched = mismatched = errors = 0
        for c in self.cases:
            try:
                got = runner(dict(c.inputs))
                c.observed = got
                c.matched = got == c.expected
                if c.matched:
                    matched += 1
                else:
                    mismatched += 1
            except Exception as exc:
                errors += 1
                c.note = f"{type(exc).__name__}: {exc}"
        self.confidence = ("observed" if matched and not mismatched and not errors
                           else "hypothesis")
        return {
            "matched": matched, "mismatched": mismatched, "errors": errors,
            "confidence": self.confidence,
            "unknowns": list(self.unknowns),
            "note": ("matching observed behaviour does not recover internal "
                     "details; scope is limited to the listed cases"),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "scope": self.scope,
            "cases": [c.to_dict() for c in self.cases],
            "unknowns": self.unknowns, "confidence": self.confidence,
        }


def detect_languages(root: str) -> dict[str, Any]:
    p = Path(root)
    counts: dict[str, int] = {}
    build: list[str] = []
    if p.is_file():
        files = [p]
    else:
        files = [x for x in p.rglob("*") if x.is_file()][:4000] if p.is_dir() else []
    for f in files:
        if f.name in _BUILD:
            build.append(_BUILD[f.name])
        lang = _LANGS.get(f.suffix.lower())
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "languages": [{"name": n, "files": c} for n, c in ranked],
        "build_systems": sorted(set(build)),
        "note": ("language prevalence is not a reason to choose a stack; "
                 "record the constraints and trade-offs first"),
    }


def language_tradeoffs(language: str) -> list[str]:
    low = language.lower()
    if low in ("rust", "c++", "c"):
        return ["strong control and performance", "manual memory/FFI risk",
                "slower iteration than a managed language"]
    if low in ("python", "ruby", "javascript", "typescript"):
        return ["fast iteration and tooling", "runtime dependency and packaging",
                "performance may need a compiled core"]
    if low in ("go",):
        return ["simple deployment and concurrency", "limited generics/abstraction",
                "larger binaries"]
    return ["unknown trade-offs; measure before choosing"]
