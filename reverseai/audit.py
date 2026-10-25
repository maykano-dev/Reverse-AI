"""Machine-readable repository audit.

This is not a substitute for running the tests or reading the code. It checks the
invariants that are easy to let drift: version consistency, required assets,
tool narration, documentation links, dependency freedom, and obvious secret
material. The result is a list of named checks, not a vague score.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*['\"][^'\"]{12,}['\"]"),
)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditReport:
    root: str
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {"root": self.root, "ok": self.ok,
                "checks": [c.to_dict() for c in self.checks]}

    def render(self) -> str:
        lines = [f"ReverseAI audit: {'PASS' if self.ok else 'FAIL'}", ""]
        for c in self.checks:
            lines.append(f"  [{'ok' if c.ok else 'FAIL'}] {c.name}"
                         + (f": {c.detail}" if c.detail else ""))
        return "\n".join(lines)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def run_audit(root: str | Path) -> AuditReport:
    root = Path(root).resolve()
    report = AuditReport(str(root))

    def add(name: str, ok: bool, detail: str = "") -> None:
        report.checks.append(Check(name, ok, detail))

    # Version and packaging.
    init = _read(root / "reverseai/__init__.py")
    pyproject = _read(root / "pyproject.toml")
    m_init = re.search(r'__version__\s*=\s*"([^"]+)"', init)
    m_proj = re.search(r'version\s*=\s*"([^"]+)"', pyproject)
    add("version is consistent",
        bool(m_init and m_proj and m_init.group(1) == m_proj.group(1)),
        f"{m_init.group(1) if m_init else '?'} / "
        f"{m_proj.group(1) if m_proj else '?'}")
    add("core has no required dependencies",
        bool(re.search(r"dependencies\s*=\s*\[\s*\]", pyproject)),
        "pyproject dependencies must stay empty")
    add("Python 3.11+",
        "requires-python" in pyproject and "3.11" in pyproject)
    try:
        from .release import feature_issues, release_truth

        truth = release_truth(root)
        add("release metadata agrees", not truth.issues, "; ".join(truth.issues))
        facts = feature_issues(root)
        add("feature claims have source and tests", not facts, "; ".join(facts))
    except Exception as exc:
        add("release consistency check", False,
            f"{type(exc).__name__}: {exc}")

    # Required assets.
    required = [
        "README.md", "CLAUDE.md", "CHANGELOG.md", "LICENSE",
        "reverseai/server/static/index.html",
        "reverseai/server/static/app.js",
        "reverseai/server/static/style.css",
        "reverseai/server/static/sw.js",
        "docs/SECURITY.md", "docs/ARCHITECTURE.md",
        "docs/INTELLIGENCE_ROADMAP.md", "docs/AUDIT_REMEDIATION.md",
        "docs/TESTING.md", "docs/DANGEROUS_AND_OPEN_ITEMS.md",
        "docs/AUDIT_0_8_0.md",
    ]
    missing = [p for p in required if not (root / p).is_file()]
    add("required files exist", not missing, ", ".join(missing))

    # Tools: contract surface, narration, and UI labels.
    try:
        from .agent.builtins import default_tools
        from .agent.narrative import describe_tool

        tools = default_tools()
        names = [t.name for t in tools]
        add("tool names are unique", len(names) == len(set(names)),
            f"{len(names)} tools")
        no_narration = [t.name for t in tools
                        if not describe_tool(t.name, {})["detail"].strip()]
        add("every tool has narration", not no_narration,
            ", ".join(no_narration))
        app = _read(root / "reverseai/server/static/app.js")
        no_label = [t.name for t in tools
                    if not re.search(re.escape(t.name) + r"\s*:", app)]
        add("every tool has a UI label", not no_label, ", ".join(no_label))
    except Exception as exc:
        add("tools import and describe", False, f"{type(exc).__name__}: {exc}")

    # Documentation links that point into this repository.
    readme = _read(root / "README.md")
    links = set(re.findall(r"\(([^)]*docs/[A-Za-z0-9_./-]+\.md)\)", readme))
    missing_links = [l for l in links if not (root / l).is_file()]
    add("README doc links resolve", not missing_links, ", ".join(missing_links))

    # Secret hygiene.
    add(".env is ignored", ".env" in _read(root / ".gitignore"))
    leaked = []
    for path in root.rglob("*"):
        if any(part in {".git", "jobs", "__pycache__", "node_modules", "dist",
                        "tests"}
               for part in path.parts):
            continue
        if path.suffix.lower() not in {".py", ".md", ".json", ".yml", ".yaml",
                                       ".toml", ".sh", ".txt", ".env"}:
            continue
        if path.name == ".env":
            leaked.append(str(path.relative_to(root)))
            continue
        text = _read(path)
        if any(p.search(text) for p in _SECRET_PATTERNS):
            leaked.append(str(path.relative_to(root)))
    add("no obvious secret material", not leaked, ", ".join(leaked[:8]))

    # Static shell must not reference remote scripts.
    index = _read(root / "reverseai/server/static/index.html")
    add("UI has no remote script tags",
        not re.search(r"<script[^>]+src=['\"]https?://", index, re.I))
    add("service worker has a version",
        "VERSION" in _read(root / "reverseai/server/static/sw.js"))

    # Test presence.
    tests = list((root / "tests").glob("test_*.py"))
    add("test suite exists", len(tests) >= 10, f"{len(tests)} test modules")

    return report


def audit_json(root: str | Path) -> str:
    return json.dumps(run_audit(root).to_dict(), indent=2)
