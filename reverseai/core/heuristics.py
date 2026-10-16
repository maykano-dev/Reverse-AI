"""Heuristic assessment derived from a static AnalysisReport.

These are *inferences*, not facts — deliberately labeled as such so the agent
records them at BELIEVED confidence. They flag packing, obfuscation, and
anti-analysis traits worth investigating, without claiming certainty.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import AnalysisReport

# Section names strongly associated with known packers.
_PACKER_SECTIONS = {
    "upx0", "upx1", "upx2", ".aspack", ".adata", ".nsp0", ".nsp1",
    "aspack", ".packed", "pec1", "pec2", ".petite", ".mpress1", ".mpress2",
    ".themida", ".vmp0", ".vmp1", ".enigma1", ".enigma2",
}


@dataclass
class Assessment:
    packing_likelihood: str = "low"   # low | medium | high
    signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def assess(report: AnalysisReport) -> Assessment:
    signals: list[str] = []
    score = 0

    # 1. Known packer section names.
    for s in report.sections:
        if s.name.lower() in _PACKER_SECTIONS:
            signals.append(f"packer-associated section name: {s.name!r}")
            score += 3

    # 2. High whole-file entropy.
    if report.entropy >= 7.2:
        signals.append(f"high overall entropy {report.entropy} (compressed/encrypted?)")
        score += 2

    # 3. Writable + executable sections (self-modifying / unpacking stub).
    for s in report.sections:
        if "w" in s.flags and "x" in s.flags:
            signals.append(f"section {s.name!r} is both writable and executable")
            score += 2

    # 4. Very small import table for a non-trivial binary (imports resolved at runtime).
    import_syms = sum(len(v) for v in report.imports.values())
    if report.fmt.value == "pe" and report.size > 50_000 and import_syms <= 5:
        signals.append(f"unusually small import table ({import_syms} symbols) "
                       "for a binary this size")
        score += 2

    # 5. Entry point not inside any section (abnormal).
    if report.entry_point is not None and report.sections:
        in_section = any(
            s.virtual_address <= report.entry_point < s.virtual_address + max(
                s.virtual_size, s.raw_size)
            for s in report.sections
        )
        # Note: PE entry is an RVA; ELF entry is a VA. Only a soft signal.
        if not in_section and report.fmt.value == "pe":
            signals.append("entry point does not fall within a named section")
            score += 1

    # 6. High-entropy executable section specifically.
    for s in report.sections:
        if "x" in s.flags and s.entropy >= 7.3:
            signals.append(f"executable section {s.name!r} has very high entropy {s.entropy}")
            score += 1

    likelihood = "low"
    if score >= 5:
        likelihood = "high"
    elif score >= 2:
        likelihood = "medium"

    return Assessment(packing_likelihood=likelihood, signals=signals)
