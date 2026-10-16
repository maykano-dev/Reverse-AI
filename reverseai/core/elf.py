"""Minimal ELF parser using only `struct`.

Scope: ELF header (class, endianness, type, machine, entry) plus the section
header table (names, addresses, sizes). Dynamic-symbol / relocation parsing is
left to a later layer or an optional `pyelftools` backend.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .models import Arch, Section

_MACHINE = {
    0x03: (Arch.X86, 32),
    0x3E: (Arch.X86_64, 64),
    0x28: (Arch.ARM, 32),
    0xB7: (Arch.ARM64, 64),
    0x08: (Arch.MIPS, 32),
    0xF3: (Arch.RISCV, 64),
}

_ET = {1: "relocatable", 2: "exe", 3: "shared-object", 4: "core"}

# Section header type / flags we surface as access hints
_SHF_WRITE = 0x1
_SHF_ALLOC = 0x2
_SHF_EXEC = 0x4


@dataclass
class ELFInfo:
    arch: Arch = Arch.UNKNOWN
    bits: int = 0
    endian: str = "little"
    entry_point: int | None = None
    binary_type: str | None = None
    sections: list[Section] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_elf(data: bytes) -> ELFInfo:
    info = ELFInfo()
    if len(data) < 64:
        info.warnings.append("file too small for ELF header")
        return info

    ei_class = data[4]  # 1 = 32-bit, 2 = 64-bit
    ei_data = data[5]  # 1 = LE, 2 = BE
    info.bits = 64 if ei_class == 2 else 32
    info.endian = "big" if ei_data == 2 else "little"
    en = ">" if ei_data == 2 else "<"

    try:
        e_type, e_machine = struct.unpack_from(en + "HH", data, 16)
    except struct.error:
        info.warnings.append("truncated ELF header")
        return info

    info.binary_type = _ET.get(e_type)
    info.arch, machine_bits = _MACHINE.get(e_machine, (Arch.UNKNOWN, info.bits))
    if machine_bits:
        info.bits = machine_bits

    try:
        if info.bits == 64:
            e_entry = struct.unpack_from(en + "Q", data, 24)[0]
            e_shoff = struct.unpack_from(en + "Q", data, 40)[0]
            e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(en + "HHH", data, 58)
        else:
            e_entry = struct.unpack_from(en + "I", data, 24)[0]
            e_shoff = struct.unpack_from(en + "I", data, 32)[0]
            e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(en + "HHH", data, 46)
        info.entry_point = e_entry
    except struct.error:
        info.warnings.append("truncated ELF header fields")
        return info

    if e_shoff and e_shnum:
        info.sections = _parse_sections(
            data, en, info.bits, e_shoff, e_shentsize, e_shnum, e_shstrndx, info.warnings
        )
    return info


def _parse_sections(data, en, bits, shoff, shentsize, shnum, shstrndx, warnings) -> list[Section]:
    from .identify import shannon_entropy

    # First locate the section-header string table to resolve names.
    def _read_shdr(i):
        base = shoff + i * shentsize
        if bits == 64:
            name, s_type, flags, addr, off, size = struct.unpack_from(en + "IIQQQQ", data, base)
        else:
            name, s_type, flags, addr, off, size = struct.unpack_from(en + "IIIIII", data, base)
        return name, s_type, flags, addr, off, size

    strtab_off = 0
    try:
        if 0 <= shstrndx < shnum:
            _, _, _, _, strtab_off, _ = _read_shdr(shstrndx)
    except struct.error:
        warnings.append("bad section string table index")

    def _name(name_off: int) -> str:
        if not strtab_off:
            return ""
        pos = strtab_off + name_off
        end = data.find(b"\x00", pos)
        return data[pos:end].decode("ascii", "replace") if end != -1 else ""

    sections: list[Section] = []
    for i in range(shnum):
        try:
            name_off, _type, flags, addr, off, size = _read_shdr(i)
        except struct.error:
            warnings.append(f"section {i} header out of bounds")
            break
        body = data[off : off + size] if (size and _type != 8) else b""  # skip NOBITS(8)
        access = ""
        if flags & _SHF_ALLOC:
            access += "r"
        if flags & _SHF_WRITE:
            access += "w"
        if flags & _SHF_EXEC:
            access += "x"
        sections.append(
            Section(
                name=_name(name_off),
                virtual_address=addr,
                virtual_size=size,
                raw_size=size,
                raw_offset=off,
                entropy=round(shannon_entropy(body), 3) if body else 0.0,
                flags=access,
            )
        )
    return sections
