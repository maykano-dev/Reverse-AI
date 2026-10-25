"""Lightweight control-flow and call graphs.

This is a static, best-effort view built from the optional capstone
disassembler. It is not a decompiler and not a proof of reachability: a linear
sweep can mix code and data. Treat blocks as *observed* structure and use the
addresses as leads for deeper analysis.

The graphs are bounded and never execute the target. They give the agent a map
for locating a change and estimating its blast radius.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .analyze import analyze_file
from .disasm import Instruction, capstone_available, disassemble_bytes
from .models import AnalysisReport, Arch
from ..security.validate import read_target

MAX_FUNCTIONS = 32
MAX_INSTRUCTIONS = 4000
MAX_BLOCK_INSTRUCTIONS = 400
MAX_BYTES_PER_FUNCTION = 8192

_UNCONDITIONAL = {"jmp", "b", "br", "bx", "ret", "retn", "retq",
                  "hlt", "ud2", "int3", "noreturn"}
_RET = {"ret", "retn", "retq", "hlt", "ud2", "int3", "noreturn"}
_CALLS = {"call", "callq", "bl", "blx", "jal", "jalr"}
_CONDITIONAL_PREFIXES = ("j", "b.", "cbz", "cbnz", "tbz", "tbnz", "loop")
_BRANCH_TARGET = re.compile(r"(?:#|\$)?(0x[0-9a-fA-F]+|[0-9a-fA-F]+)")


@dataclass
class BasicBlock:
    address: int
    end: int
    instructions: list[dict[str, Any]] = field(default_factory=list)
    successors: list[int] = field(default_factory=list)
    terminator: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "end": self.end,
            "successors": self.successors,
            "terminator": self.terminator,
            "instruction_count": len(self.instructions),
            "instructions": self.instructions[:24],
        }


@dataclass
class FunctionGraph:
    name: str
    address: int
    size: int
    blocks: list[BasicBlock] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def edges(self) -> int:
        return sum(len(b.successors) for b in self.blocks)

    @property
    def cyclomatic_complexity(self) -> int:
        return max(0, self.edges - len(self.blocks) + 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "address": self.address,
            "size": self.size,
            "blocks": [b.to_dict() for b in self.blocks],
            "block_count": len(self.blocks),
            "edge_count": self.edges,
            "cyclomatic_complexity": self.cyclomatic_complexity,
            "calls": self.calls[:200],
            "warnings": self.warnings,
        }


@dataclass
class ControlFlowReport:
    path: str
    architecture: str
    functions: list[FunctionGraph] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "architecture": self.architecture,
            "functions": [f.to_dict() for f in self.functions],
            "function_count": len(self.functions),
            "block_count": sum(len(f.blocks) for f in self.functions),
            "edge_count": sum(f.edges for f in self.functions),
            "call_count": sum(len(f.calls) for f in self.functions),
            "warnings": self.warnings,
        }


def _target(op_str: str) -> int | None:
    text = (op_str or "").strip()
    if not text or "[" in text or "rip" in text:
        return None
    m = _BRANCH_TARGET.search(text)
    if not m:
        return None
    try:
        return int(m.group(1), 0) if m.group(1).lower().startswith("0x") else int(
            m.group(1), 16)
    except ValueError:
        return None


def _is_branch(mnemonic: str) -> bool:
    m = mnemonic.lower()
    if m in _UNCONDITIONAL or m in _CALLS:
        return True
    return any(m.startswith(p) for p in _CONDITIONAL_PREFIXES)


def _is_conditional(mnemonic: str) -> bool:
    m = mnemonic.lower()
    if m in _RET or m == "jmp" or m in ("b", "br", "bx"):
        return False
    return any(m.startswith(p) for p in _CONDITIONAL_PREFIXES) or m.startswith("j")


def build_cfg(instructions: list[Instruction], name: str = "function",
              address: int | None = None) -> FunctionGraph:
    """Build basic blocks and successor edges from a linear instruction list."""
    if not instructions:
        return FunctionGraph(name=name, address=address or 0, size=0)
    ordered = sorted(instructions, key=lambda i: i.address)
    if address is None:
        address = ordered[0].address
    by_addr = {i.address: i for i in ordered}
    leaders = {ordered[0].address}
    for ins in ordered:
        m = ins.mnemonic.lower()
        if _is_branch(m):
            t = _target(ins.op_str)
            if t is not None and t in by_addr:
                leaders.add(t)
            nxt = ins.address + ins.size
            if nxt in by_addr:
                leaders.add(nxt)
    starts = sorted(a for a in leaders if a in by_addr)
    if not starts:
        starts = [ordered[0].address]

    blocks: list[BasicBlock] = []
    warnings: list[str] = []
    for idx, start in enumerate(starts):
        end_addr = starts[idx + 1] if idx + 1 < len(starts) else None
        block_ins: list[Instruction] = []
        cursor = start
        while cursor in by_addr:
            if end_addr is not None and cursor >= end_addr:
                break
            ins = by_addr[cursor]
            block_ins.append(ins)
            if len(block_ins) >= MAX_BLOCK_INSTRUCTIONS:
                warnings.append(f"block at 0x{start:x} truncated")
                break
            cursor += ins.size
            if _is_branch(ins.mnemonic.lower()) and not _is_conditional(
                    ins.mnemonic.lower()):
                break
            if _is_conditional(ins.mnemonic.lower()):
                break
        if not block_ins:
            continue
        term = block_ins[-1]
        succ: list[int] = []
        m = term.mnemonic.lower()
        if m in _RET:
            pass
        elif m in _CALLS:
            nxt = term.address + term.size
            if nxt in by_addr:
                succ.append(nxt)
        elif _is_conditional(m):
            t = _target(term.op_str)
            if t in by_addr:
                succ.append(t)
            nxt = term.address + term.size
            if nxt in by_addr:
                succ.append(nxt)
        elif _is_branch(m):
            t = _target(term.op_str)
            if t in by_addr:
                succ.append(t)
        else:
            nxt = term.address + term.size
            if nxt in by_addr:
                succ.append(nxt)
        blocks.append(BasicBlock(
            address=block_ins[0].address,
            end=block_ins[-1].address + block_ins[-1].size,
            instructions=[{
                "address": i.address, "mnemonic": i.mnemonic,
                "op_str": i.op_str, "size": i.size,
            } for i in block_ins],
            successors=sorted(set(succ)),
            terminator=f"{term.mnemonic} {term.op_str}".strip(),
        ))
    calls: list[dict[str, Any]] = []
    for ins in ordered:
        if ins.mnemonic.lower() in _CALLS:
            calls.append({"address": ins.address, "target": _target(ins.op_str)})
    size = (ordered[-1].address + ordered[-1].size) - ordered[0].address
    return FunctionGraph(name=name, address=ordered[0].address, size=size,
                         blocks=blocks, calls=calls, warnings=warnings)


def _section_for(report: AnalysisReport, addr: int):
    for s in report.sections:
        span = max(s.virtual_size, s.raw_size)
        if s.virtual_address <= addr < s.virtual_address + span:
            return s
    return None


def _function_bytes(data: bytes, report: AnalysisReport, addr: int,
                    size: int) -> tuple[bytes, int] | None:
    section = _section_for(report, addr)
    if section is None:
        return None
    offset = section.raw_offset + (addr - section.virtual_address)
    if offset < 0 or offset >= len(data):
        return None
    if size <= 0:
        size = max(0, min(MAX_BYTES_PER_FUNCTION,
                           section.raw_offset + section.raw_size - offset))
    size = min(size, MAX_BYTES_PER_FUNCTION, len(data) - offset)
    if size <= 0:
        return None
    return data[offset:offset + size], addr


def analyze_control_flow(path: str, report: AnalysisReport | None = None,
                         max_functions: int = MAX_FUNCTIONS) -> ControlFlowReport:
    """Build graphs for up to ``max_functions`` functions. Never executes code."""
    report = report or analyze_file(path)
    out = ControlFlowReport(path=str(path), architecture=report.arch.value)
    if not capstone_available():
        out.warnings.append("capstone is not installed; control-flow analysis is unavailable")
        return out
    if report.arch is Arch.UNKNOWN:
        out.warnings.append("the architecture is unknown; cannot disassemble")
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
        text = next((s for s in report.sections
                     if s.name.lower() in (".text", "__text")), None)
        if text is not None:
            functions = [{"name": "text", "address": text.virtual_address, "size": 0}]
    if not functions:
        out.warnings.append("no functions or executable entry point were found")
        return out

    for f in functions[:max_functions]:
        addr = int(f.get("address") or 0)
        size = int(f.get("size") or 0)
        name = str(f.get("name") or f"sub_{addr:x}")
        if addr <= 0:
            continue
        got = _function_bytes(data, report, addr, size)
        if got is None:
            out.warnings.append(f"function {name} at 0x{addr:x} is not in a mapped section")
            continue
        blob, base = got
        try:
            insns = disassemble_bytes(blob, report.arch, base_address=base,
                                      count=MAX_INSTRUCTIONS)
        except RuntimeError as exc:
            out.warnings.append(str(exc))
            break
        if not insns:
            continue
        graph = build_cfg(insns, name=name, address=base)
        if size:
            graph.size = size
        out.functions.append(graph)
    if len(functions) > max_functions:
        out.warnings.append(
            f"only the first {max_functions} of {len(functions)} functions were graphed")
    return out
