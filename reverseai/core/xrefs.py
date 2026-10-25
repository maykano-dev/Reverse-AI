"""Bounded cross-references from recovered code.

This is a static, best-effort map of direct call/jump targets. It does not
resolve indirect calls through registers or memory, and a linear sweep can mix
code and data. Use it as a lead, not as a complete call graph.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .analyze import analyze_file
from .disasm import Instruction, capstone_available, disassemble_bytes
from .models import AnalysisReport
from ..security.validate import read_target

MAX_FUNCTIONS = 80
MAX_INSTRUCTIONS = 5000
MAX_BYTES = 8192
_TARGET = re.compile(r"(?:#|\$)?(0x[0-9a-fA-F]+|[0-9a-fA-F]+)")
_BRANCH = ("call", "callq", "bl", "blx", "jal", "jalr", "jmp", "b", "br")


@dataclass
class XRef:
    from_address: int
    to_address: int | None
    kind: str
    function: str = ""
    direct: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class XRefReport:
    path: str
    refs: list[XRef] = field(default_factory=list)
    functions: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def callers_of(self, name: str) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.refs
                if r.kind in ("call", "callq", "bl", "blx", "jal", "jalr")
                and self._target_name(r.to_address) == name]

    def callees_of(self, name: str) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.refs
                if r.function == name and r.to_address is not None]

    def _target_name(self, address: int | None) -> str:
        for name, info in self.functions.items():
            if info.get("address") == address:
                return name
        return f"0x{address:x}" if address is not None else "(indirect)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "refs": [r.to_dict() for r in self.refs],
            "functions": self.functions,
            "warnings": self.warnings,
            "count": len(self.refs),
        }


def _target(op_str: str) -> int | None:
    text = (op_str or "").strip()
    if not text or "[" in text or "rip" in text:
        return None
    m = _TARGET.search(text)
    if not m:
        return None
    try:
        raw = m.group(1)
        return int(raw, 0) if raw.lower().startswith("0x") else int(raw, 16)
    except ValueError:
        return None


def _section_for(report: AnalysisReport, addr: int):
    for s in report.sections:
        span = max(s.virtual_size, s.raw_size)
        if s.virtual_address <= addr < s.virtual_address + span:
            return s
    return None


def find_xrefs(path: str, report: AnalysisReport | None = None,
               max_functions: int = MAX_FUNCTIONS) -> XRefReport:
    report = report or analyze_file(path)
    out = XRefReport(path=str(path))
    if not capstone_available():
        out.warnings.append("capstone is not installed; xrefs are unavailable")
        return out
    try:
        data = read_target(path)
    except Exception as exc:
        out.warnings.append(f"could not read the target: {exc}")
        return out
    functions = list(report.functions)
    if not functions and report.entry_point is not None:
        functions = [{"name": "entry", "address": report.entry_point, "size": 0}]
    if not functions:
        out.warnings.append("no functions or entry point were recovered")
        return out
    for raw in functions[:max_functions]:
        name = str(raw.get("name") or "sub")
        addr = int(raw.get("address") or 0)
        size = int(raw.get("size") or 0)
        section = _section_for(report, addr)
        if section is None or addr <= 0:
            continue
        offset = section.raw_offset + (addr - section.virtual_address)
        if offset < 0 or offset >= len(data):
            continue
        if size <= 0:
            size = min(MAX_BYTES, section.raw_offset + section.raw_size - offset)
        blob = data[offset:offset + min(size, MAX_BYTES, len(data) - offset)]
        if not blob:
            continue
        try:
            insns = disassemble_bytes(blob, report.arch, base_address=addr,
                                      count=MAX_INSTRUCTIONS)
        except RuntimeError as exc:
            out.warnings.append(str(exc))
            break
        out.functions[name] = {"address": addr, "size": size,
                               "instructions": len(insns)}
        for ins in insns:
            m = ins.mnemonic.lower()
            if m not in _BRANCH:
                continue
            target = _target(ins.op_str)
            out.refs.append(XRef(ins.address, target, m, name, target is not None))
        if len(out.refs) > 10000:
            out.warnings.append("xref list truncated")
            break
    return out
