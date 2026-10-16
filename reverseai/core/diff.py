"""Structural diff between two binaries (via their AnalysisReports).

Complements behavioral verification: where `verify/` runs both binaries and
compares observable behavior, this compares static structure — which sections,
imports, exports, and bytes changed. Together they answer "what changed, and
did it matter?"
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .analyze import analyze_file
from .models import AnalysisReport


@dataclass
class BinaryDiff:
    identical: bool
    same_format: bool
    same_arch: bool
    size_delta: int
    entropy_delta: float
    sections_added: list[str] = field(default_factory=list)
    sections_removed: list[str] = field(default_factory=list)
    sections_changed: list[dict[str, Any]] = field(default_factory=list)
    imports_added: list[str] = field(default_factory=list)
    imports_removed: list[str] = field(default_factory=list)
    exports_added: list[str] = field(default_factory=list)
    exports_removed: list[str] = field(default_factory=list)
    needed_added: list[str] = field(default_factory=list)
    needed_removed: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _flat_imports(r: AnalysisReport) -> set[str]:
    out: set[str] = set()
    for lib, syms in r.imports.items():
        for s in syms:
            out.add(f"{lib}!{s}")
    out.update(r.dynamic_symbols)
    return out


def diff_reports(a: AnalysisReport, b: AnalysisReport) -> BinaryDiff:
    a_secs = {s.name: s for s in a.sections}
    b_secs = {s.name: s for s in b.sections}

    changed = []
    for name in a_secs.keys() & b_secs.keys():
        sa, sb = a_secs[name], b_secs[name]
        if (sa.raw_size, sa.virtual_size, sa.entropy, sa.flags) != (
            sb.raw_size, sb.virtual_size, sb.entropy, sb.flags
        ):
            changed.append({
                "name": name,
                "raw_size": [sa.raw_size, sb.raw_size],
                "entropy": [sa.entropy, sb.entropy],
                "flags": [sa.flags, sb.flags],
            })

    a_imp, b_imp = _flat_imports(a), _flat_imports(b)
    a_exp, b_exp = set(a.exports), set(b.exports)
    a_need, b_need = set(a.needed_libraries), set(b.needed_libraries)

    identical = a.hashes.get("sha256") == b.hashes.get("sha256") and bool(a.hashes)

    d = BinaryDiff(
        identical=identical,
        same_format=a.fmt == b.fmt,
        same_arch=a.arch == b.arch,
        size_delta=b.size - a.size,
        entropy_delta=round(b.entropy - a.entropy, 3),
        sections_added=sorted(b_secs.keys() - a_secs.keys()),
        sections_removed=sorted(a_secs.keys() - b_secs.keys()),
        sections_changed=changed,
        imports_added=sorted(b_imp - a_imp),
        imports_removed=sorted(a_imp - b_imp),
        exports_added=sorted(b_exp - a_exp),
        exports_removed=sorted(a_exp - b_exp),
        needed_added=sorted(b_need - a_need),
        needed_removed=sorted(a_need - b_need),
    )
    d.summary = _summarize(d)
    return d


def diff_files(path_a: str, path_b: str) -> BinaryDiff:
    return diff_reports(analyze_file(path_a), analyze_file(path_b))


def _summarize(d: BinaryDiff) -> str:
    if d.identical:
        return "identical (same sha256)"
    parts = [f"size {d.size_delta:+d}B", f"entropy {d.entropy_delta:+.3f}"]
    if d.sections_added:
        parts.append(f"+{len(d.sections_added)} sections")
    if d.sections_removed:
        parts.append(f"-{len(d.sections_removed)} sections")
    if d.sections_changed:
        parts.append(f"{len(d.sections_changed)} sections changed")
    if d.imports_added:
        parts.append(f"+{len(d.imports_added)} imports")
    if d.imports_removed:
        parts.append(f"-{len(d.imports_removed)} imports")
    if not d.same_arch:
        parts.append("ARCH CHANGED")
    return ", ".join(parts)
