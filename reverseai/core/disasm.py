"""Disassembly helpers.

Preferred path uses capstone (optional). When capstone is absent, the caller
can fall back to objdump — but objdump must parse the *untrusted* target, so it
should be run inside the sandbox, not here. This module only does the pure,
in-process capstone path over bytes already extracted.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Arch


@dataclass
class Instruction:
    address: int
    mnemonic: str
    op_str: str
    size: int
    bytes_hex: str

    def __str__(self) -> str:
        return f"0x{self.address:x}:\t{self.mnemonic}\t{self.op_str}".rstrip()


def capstone_available() -> bool:
    try:
        import capstone  # noqa: F401

        return True
    except ImportError:
        return False


_CS_MAP = {
    Arch.X86: ("CS_ARCH_X86", "CS_MODE_32"),
    Arch.X86_64: ("CS_ARCH_X86", "CS_MODE_64"),
    Arch.ARM: ("CS_ARCH_ARM", "CS_MODE_ARM"),
    Arch.ARM64: ("CS_ARCH_ARM64", "CS_MODE_ARM"),
    Arch.MIPS: ("CS_ARCH_MIPS", "CS_MODE_MIPS32"),
}


def disassemble_bytes(
    code: bytes, arch: Arch, base_address: int = 0, count: int = 0
) -> list[Instruction]:
    """Linear disassembly with capstone. Raises RuntimeError if capstone is
    unavailable or the architecture is unsupported.

    ``count`` of 0 disassembles everything; otherwise stops after N instructions.
    """
    try:
        import capstone
    except ImportError as exc:  # pragma: no cover - env dependent
        raise RuntimeError("capstone not installed (pip install capstone)") from exc

    if arch not in _CS_MAP:
        raise RuntimeError(f"unsupported architecture for disassembly: {arch.value}")

    arch_name, mode_name = _CS_MAP[arch]
    md = capstone.Cs(getattr(capstone, arch_name), getattr(capstone, mode_name))
    out: list[Instruction] = []
    for insn in md.disasm(code, base_address):
        out.append(
            Instruction(
                address=insn.address,
                mnemonic=insn.mnemonic,
                op_str=insn.op_str,
                size=insn.size,
                bytes_hex=insn.bytes.hex(),
            )
        )
        if count and len(out) >= count:
            break
    return out
