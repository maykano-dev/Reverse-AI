"""Agent templates — the unified "roles/squads" layer.

Every major agent product ships some notion of a specialist: a researcher, a
coder, a reviewer, a security analyst. ReverseAI keeps one engine and swaps the
instructions, default permission, and starter prompts. Templates are also used
by the ``delegate`` tool, which is how a lead agent hands work to a specialist.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AgentTemplate:
    id: str
    name: str
    icon: str
    description: str
    addendum: str
    permission: str = "write"
    suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_TEMPLATES: dict[str, AgentTemplate] = {
    "general": AgentTemplate(
        id="general",
        name="Everyday",
        icon="sparkle",
        description="A capable assistant for anything: questions, files, code, research.",
        addendum=(
            "You are in everyday mode. Be warm, direct, and useful. Use tools only "
            "when they genuinely help; otherwise answer or ask one short question."
        ),
        suggestions=[
            "Explain what this file does in plain language.",
            "Look into this app and tell me what stands out.",
            "Build me a small tool that does this.",
        ],
    ),
    "reverse": AgentTemplate(
        id="reverse",
        name="Reverse engineer",
        icon="cpu",
        description="Understand, modify, and rebuild compiled software.",
        addendum=(
            "You are in reverse-engineering mode. Start from the real bytes, not "
            "guesses. Prefer decompilation to raw disassembly when available. Work "
            "on copies, verify behavior in the sandbox, and separate observed facts "
            "from inferences. Deliver a working artifact with a clear name."
        ),
        suggestions=[
            "Analyze this binary and explain what it does.",
            "Run it safely and show me its real behavior.",
            "Change this behavior and give me a verified modified file.",
        ],
    ),
    "engineer": AgentTemplate(
        id="engineer",
        name="Engineer",
        icon="code",
        description="Read, write, debug, and test code in a project.",
        addendum=(
            "You are in engineering mode. Inspect the project before editing, make "
            "the smallest coherent change, run the relevant tests, and report exactly "
            "what changed and what passed. Prefer real test output over assurances."
        ),
        suggestions=[
            "Find and fix the bug in this project.",
            "Add tests for the code I just changed.",
            "Refactor this module without changing behavior.",
        ],
    ),
    "researcher": AgentTemplate(
        id="researcher",
        name="Researcher",
        icon="search",
        description="Search the web, read sources, and answer with citations.",
        addendum=(
            "You are in research mode. Search, read primary sources, and answer with "
            "a short synthesis and a Sources section. Never invent a citation. If "
            "the evidence is thin, say so plainly."
        ),
        suggestions=[
            "Research this topic and cite reliable sources.",
            "Compare these options and recommend one.",
            "Find the latest information about this and summarize it.",
        ],
    ),
    "security": AgentTemplate(
        id="security",
        name="Security",
        icon="alert",
        description="Defensive review, malware indicators, and safe testing.",
        addendum=(
            "You are in defensive-security mode. Treat every artifact as hostile. "
            "Analyze statically first, run only in the sandbox, and never exfiltrate "
            "data or weaken containment. Report risk with evidence and confidence."
        ),
        suggestions=[
            "Check this file for malware indicators.",
            "Review this project for security problems.",
            "Explain how this sample behaves without running it on my machine.",
        ],
    ),
    "mobile": AgentTemplate(
        id="mobile",
        name="Mobile",
        icon="box",
        description="Android APK and iOS artifact analysis.",
        addendum=(
            "You are in mobile-analysis mode. Inspect the package structure, "
            "manifest, permissions, DEX, and native libraries. Be explicit about what "
            "needs external tooling such as apktool, jadx, or apksigner."
        ),
        suggestions=[
            "Analyze this APK: permissions, ABI, and native libraries.",
            "What does this app talk to, based on its strings and libraries?",
            "Check this mobile app for risky permissions.",
        ],
    ),
    "writer": AgentTemplate(
        id="writer",
        name="Writer",
        icon="file",
        description="Draft posts, docs, emails, and clear explanations.",
        addendum=(
            "You are in writing mode. Match the user's voice, lead with the point, "
            "cut filler, and keep a natural rhythm. Do not use em dashes or en dashes."
        ),
        suggestions=[
            "Write a launch post for this project.",
            "Turn these notes into a clear README.",
            "Explain this to a non-technical reader.",
        ],
    ),
    "data": AgentTemplate(
        id="data",
        name="Data",
        icon="bars",
        description="Parse, compare, and explain datasets and logs.",
        addendum=(
            "You are in data mode. Inspect the schema first, state assumptions, keep "
            "a reproducible trail, and show the numbers that support each conclusion."
        ),
        suggestions=[
            "Summarize this dataset and flag anomalies.",
            "Compare these two files and explain the differences.",
            "Build a small script that cleans this data.",
        ],
    ),
}


def all_templates() -> list[AgentTemplate]:
    return list(_TEMPLATES.values())


def get_template(template_id: str | None) -> AgentTemplate:
    return _TEMPLATES.get((template_id or "general").lower(), _TEMPLATES["general"])


def prompt_addendum(template_id: str | None) -> str:
    return get_template(template_id).addendum


def template_permission(template_id: str | None) -> str:
    return get_template(template_id).permission


# Keyword signals used to auto-pick a specialist from the user's request, so the
# role is delegated in the background instead of chosen from a dropdown. Ordered
# most-specific first; ties break toward the earlier entry.
_SIGNALS: list[tuple[str, tuple[str, ...]]] = [
    ("security", ("vulnerability", "vulnerabilities", "exploit", "cve",
                  "malware", "pentest", "penetration test", "injection",
                  "security review", "sql injection", "buffer overflow",
                  "harden", "backdoor", "is this safe", "scan for")),
    ("reverse", ("reverse engineer", "decompile", "disassemble", "binary",
                 "executable", " exe", ".exe", ".dll", "firmware", "elf",
                 "mach-o", "assembly", "byte patch", "patch the", "unpack",
                 "crack", "shared object", ".so ", "opcode", "port this",
                 "port the", "port it", "legacy app", "windows app")),
    ("mobile", ("android", "apk", " ios", "ipa", "mobile app", "smali",
                "play store", "app store")),
    ("data", ("csv", "json", "dataset", "spreadsheet", "parse the",
              "log file", "logs", "data set", "analyze this data",
              "columns", "rows of")),
    ("researcher", ("research", "look up", "search the web", "find sources",
                    "cite", "citation", "latest news", "look into this topic",
                    "investigate online", "find out about")),
    ("writer", ("write a", "draft", "email", "blog post", "essay", "article",
                "rewrite", "proofread", "copy for", "write me a post")),
    ("engineer", ("fix the bug", "refactor", "unit test", "add tests",
                  "this repo", "this project", "codebase", "implement a",
                  "compile", "build the", "pull request", "function in")),
]


def classify_goal(goal: str | None) -> str:
    """Pick the best-fit specialist id for a request. Falls back to 'general'.

    Deterministic keyword scoring — no model call — so background delegation is
    instant and predictable. Returns 'general' when nothing clearly matches.
    """
    text = f" {(goal or '').lower()} "
    best_id, best_score = "general", 0
    for tid, words in _SIGNALS:
        score = sum(1 for w in words if w in text)
        if score > best_score:
            best_id, best_score = tid, score
    return best_id


def resolve_template(template_id: str | None, goal: str | None) -> str:
    """Resolve a requested template, auto-classifying when it's 'auto'/empty."""
    tid = (template_id or "").strip().lower()
    if tid in ("", "auto"):
        return classify_goal(goal)
    return tid if tid in _TEMPLATES else "general"
