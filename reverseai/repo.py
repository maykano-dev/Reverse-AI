"""Bounded source-repository understanding.

This is a structural map, not a compiler. It inventories files, languages,
build systems, imports, entry points, tests, and obvious risk markers. It gives
the agent a repository-wide starting point before it opens individual files.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .intelligence.product import detect_languages

MAX_FILES = 2500
MAX_FILE_BYTES = 512 * 1024
_SKIP = {".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__",
         ".mypy_cache", ".pytest_cache", "target", "vendor"}
_LANG = {
    ".py": "Python", ".rs": "Rust", ".go": "Go", ".c": "C", ".h": "C/C++",
    ".cc": "C++", ".cpp": "C++", ".java": "Java", ".kt": "Kotlin",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript",
    ".jsx": "JavaScript", ".cs": "C#", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".scala": "Scala", ".sh": "Shell", ".sql": "SQL",
}
_ENTRY = {"main.py", "app.py", "server.py", "cli.py", "index.js", "index.ts",
          "main.go", "main.rs", "lib.rs", "main.c", "main.cpp", "Main.java",
          "Program.cs", "app.rb"}
_IMPORT_PATTERNS = {
    "Python": [re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", re.M)],
    "JavaScript": [re.compile(r"from\s+['\"]([^'\"]+)['\"]"),
                   re.compile(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)")],
    "TypeScript": [re.compile(r"from\s+['\"]([^'\"]+)['\"]"),
                   re.compile(r"require\(\s*['\"]([^'\"]+)['\"]\s*\)")],
    "Go": [re.compile(r"^\s*\"([^\"]+)\"", re.M)],
    "Rust": [re.compile(r"^\s*use\s+([A-Za-z_][\w:]*)", re.M)],
    "Java": [re.compile(r"^\s*import\s+([\w.]+);", re.M)],
}
_RISK = re.compile(r"(?i)\b(TODO|FIXME|HACK|XXX|password|secret|token)\b")


@dataclass
class RepoFile:
    path: str
    language: str
    lines: int
    bytes: int
    is_test: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepoModel:
    root: str
    files: list[RepoFile] = field(default_factory=list)
    languages: list[dict[str, Any]] = field(default_factory=list)
    build_systems: list[str] = field(default_factory=list)
    imports: dict[str, list[str]] = field(default_factory=dict)
    entry_points: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    risk_markers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "files": len(self.files),
            "languages": self.languages,
            "build_systems": self.build_systems,
            "entry_points": self.entry_points,
            "tests": len(self.tests),
            "imports": len(self.imports),
            "risk_markers": len(self.risk_markers),
            "warnings": self.warnings,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "summary": self.summary(),
            "files": [f.to_dict() for f in self.files],
            "languages": self.languages,
            "build_systems": self.build_systems,
            "imports": self.imports,
            "entry_points": self.entry_points,
            "tests": self.tests,
            "risk_markers": self.risk_markers,
            "warnings": self.warnings,
        }


def _safe_file(path: Path) -> bool:
    return (path.is_file() and not path.is_symlink()
            and path.stat().st_size <= MAX_FILE_BYTES)


def build_repo_model(root: str | Path) -> RepoModel:
    base = Path(root).resolve()
    if not base.is_dir():
        raise ValueError(f"not a directory: {root}")
    model = RepoModel(str(base))
    languages = detect_languages(str(base))
    model.languages = languages["languages"]
    model.build_systems = languages["build_systems"]
    count = 0
    for path in sorted(base.rglob("*")):
        if count >= MAX_FILES:
            model.warnings.append(f"file limit reached ({MAX_FILES})")
            break
        if any(part in _SKIP for part in path.parts):
            continue
        if not _safe_file(path):
            continue
        try:
            resolved = path.resolve()
            if not resolved.is_relative_to(base):
                continue
            rel = str(path.relative_to(base))
        except (OSError, ValueError):
            continue
        lang = _LANG.get(path.suffix.lower(), "")
        if not lang:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        count += 1
        is_test = bool(re.search(r"(^|/)(tests?|spec|__tests__)(/|$)", rel)
                       or re.search(r"(test_|_test|\.spec\.|\.test\.)", path.name))
        f = RepoFile(rel, lang, text.count("\n") + 1, len(text.encode()), is_test)
        model.files.append(f)
        if is_test:
            model.tests.append(rel)
        if path.name in _ENTRY:
            model.entry_points.append(rel)
        imports = set()
        for pat in _IMPORT_PATTERNS.get(lang, []):
            imports.update(m.group(1) for m in pat.finditer(text))
        if imports:
            model.imports[rel] = sorted(imports)[:200]
        for m in _RISK.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            model.risk_markers.append({
                "path": rel, "line": line, "marker": m.group(1),
                "context": text[max(0, m.start() - 40):m.start() + 80].strip(),
            })
            if len(model.risk_markers) >= 200:
                break
    model.entry_points = sorted(set(model.entry_points))[:50]
    model.tests = sorted(set(model.tests))[:200]
    if not model.files:
        model.warnings.append("no recognized source files")
    return model
