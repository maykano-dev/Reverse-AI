"""Data models for ReverseAI analysis.

These are plain dataclasses that serialize cleanly to JSON. They are the
contract between the analysis engine, the (future) AI agent, and the API.
Keep them dependency-free and stable.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class BinaryFormat(str, Enum):
    PE = "pe"
    ELF = "elf"
    MACHO = "macho"
    UNKNOWN = "unknown"


class Arch(str, Enum):
    X86 = "x86"
    X86_64 = "x86_64"
    ARM = "arm"
    ARM64 = "arm64"
    MIPS = "mips"
    RISCV = "riscv"
    UNKNOWN = "unknown"


@dataclass
class Section:
    name: str
    virtual_address: int = 0
    virtual_size: int = 0
    raw_size: int = 0
    raw_offset: int = 0
    entropy: float = 0.0
    flags: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnalysisReport:
    """The structured truth about one binary.

    Every field is evidence-based: it reflects what was actually parsed out of
    the file, not inference. Inference and hypotheses belong to a later layer.
    """

    path: str
    size: int
    fmt: BinaryFormat = BinaryFormat.UNKNOWN
    arch: Arch = Arch.UNKNOWN
    bits: int = 0
    endian: str = "little"
    hashes: dict[str, str] = field(default_factory=dict)
    entropy: float = 0.0

    # format-specific, best-effort
    entry_point: int | None = None
    timestamp: int | None = None
    subsystem: str | None = None
    binary_type: str | None = None  # exe / dll / shared-object / etc.
    sections: list[Section] = field(default_factory=list)
    imports: dict[str, list[str]] = field(default_factory=dict)  # lib -> symbols
    exports: list[str] = field(default_factory=list)             # exported symbol names
    needed_libraries: list[str] = field(default_factory=list)    # ELF DT_NEEDED / PE libs
    dynamic_symbols: list[str] = field(default_factory=list)     # ELF imported (undefined) syms
    functions: list[dict[str, Any]] = field(default_factory=list)  # {name,address,size}

    strings_sample: list[str] = field(default_factory=list)
    string_count: int = 0

    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fmt"] = self.fmt.value
        d["arch"] = self.arch.value
        d["sections"] = [s.to_dict() for s in self.sections]
        return d
