"""Reusable skills — markdown playbooks the agent can load on demand.

This mirrors the skills layer in Claude Code / OpenCode, kept deliberately
simple: each skill is a markdown file with optional frontmatter::

    ---
    name: elf-triage
    description: Triage an unknown ELF binary
    ---
    Steps ...

Skills live under ``REVERSEAI_SKILLS`` or ``<store>/skills``. The prompt gets
only names + descriptions; the full content is loaded by the ``read_skill``
tool when relevant, which keeps context small.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class Skill:
    name: str
    description: str
    path: str
    body: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("body", None)
        return d


def _parse(path: Path) -> Skill | None:
    try:
        text = path.read_text("utf-8")
    except OSError:
        return None
    name = path.stem
    description = ""
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            front, body = parts[1], parts[2]
            for line in front.splitlines():
                key, _, value = line.partition(":")
                key, value = key.strip().lower(), value.strip()
                if key == "name" and value:
                    name = value
                elif key == "description" and value:
                    description = value
    if not description:
        for line in body.splitlines():
            line = re.sub(r"^#+\s*", "", line).strip()
            if line:
                description = line[:160]
                break
    return Skill(name=name, description=description, path=str(path), body=body.strip())


def load_skills(root: str | os.PathLike | None) -> list[Skill]:
    if not root:
        return []
    base = Path(root)
    if not base.is_dir():
        return []
    out: list[Skill] = []
    for p in sorted(base.glob("*.md")):
        s = _parse(p)
        if s:
            out.append(s)
    return out


def skills_prompt(skills: list[Skill]) -> str:
    if not skills:
        return ""
    lines = ["Available skills (load with read_skill when one fits):"]
    for s in skills:
        lines.append(f"- {s.name}: {s.description}")
    return "\n".join(lines)


def find_skill(skills: list[Skill], name: str) -> Skill | None:
    needle = (name or "").strip().lower()
    for s in skills:
        if s.name.lower() == needle:
            return s
    for s in skills:
        if needle and needle in s.name.lower():
            return s
    return None
