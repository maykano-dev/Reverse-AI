"""Minimal Mach-O parser (header + segment sections) using only `struct`.

Scope: identify architecture/bitness/type and enumerate sections from
LC_SEGMENT / LC_SEGMENT_64 load commands. Fat/universal binaries are detected
upstream; this parses a single-arch ("thin") Mach-O, the common case.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .models import Arch, Section

# CPU types (bit 0x01000000 marks 64-bit)
_CPU = {
    7: (Arch.X86, 32),
    0x01000007: (Arch.X86_64, 64),
    12: (Arch.ARM, 32),
    0x0100000C: (Arch.ARM64, 64),
}

_FILETYPE = {0x1: "object", 0x2: "exe", 0x5: "core", 0x6: "dylib", 0x8: "bundle"}

# first four bytes on disk -> (struct endian prefix, is_64bit)
_MAGIC = {
    b"\xcf\xfa\xed\xfe": ("<", True),   # 64-bit little-endian (x86_64 / arm64)
    b"\xce\xfa\xed\xfe": ("<", False),  # 32-bit little-endian
    b"\xfe\xed\xfa\xcf": (">", True),   # 64-bit big-endian
    b"\xfe\xed\xfa\xce": (">", False),  # 32-bit big-endian
}

_LC_SEGMENT = 0x1
_LC_SEGMENT_64 = 0x19
_LC_SYMTAB = 0x2
_LC_LOAD_DYLIB = 0xC
_LC_ID_DYLIB = 0xD
_LC_LOAD_WEAK_DYLIB = 0x80000018
_LC_REEXPORT_DYLIB = 0x8000001F
_LC_LAZY_LOAD_DYLIB = 0x20
_LC_LOAD_UPWARD_DYLIB = 0x80000023
_DYLIB_COMMANDS = {_LC_LOAD_DYLIB, _LC_ID_DYLIB, _LC_LOAD_WEAK_DYLIB,
                   _LC_REEXPORT_DYLIB, _LC_LAZY_LOAD_DYLIB,
                   _LC_LOAD_UPWARD_DYLIB}

# nlist n_type masks
_N_STAB = 0xE0
_N_TYPE = 0x0E
_N_EXT = 0x01
_N_UNDF = 0x0
_N_SECT = 0xE


_FAT_MAGIC = b"\xca\xfe\xba\xbe"   # 32-bit fat (offsets are u32)
_FAT_MAGIC_64 = b"\xca\xfe\xba\xbf"  # 64-bit fat (offsets are u64)

# Preference order when a fat binary carries multiple slices.
_ARCH_PREFERENCE = [Arch.ARM64, Arch.X86_64, Arch.ARM, Arch.X86]


@dataclass
class MachOInfo:
    arch: Arch = Arch.UNKNOWN
    bits: int = 0
    endian: str = "little"
    binary_type: str | None = None
    is_fat: bool = False
    slice_count: int = 0
    sections: list[Section] = field(default_factory=list)
    dynamic_symbols: list[str] = field(default_factory=list)  # imported (undefined)
    dylibs: list[str] = field(default_factory=list)           # LC_LOAD_DYLIB family
    exports: list[str] = field(default_factory=list)
    functions: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_macho(data: bytes) -> MachOInfo:
    info = MachOInfo()
    if len(data) < 28:
        info.warnings.append("file too small for Mach-O header")
        return info

    if data[:4] in (_FAT_MAGIC, _FAT_MAGIC_64):
        return _parse_fat(data)

    magic = _MAGIC.get(data[:4])
    if magic is None:
        info.warnings.append("not a thin Mach-O (unknown magic)")
        return info
    en, is64 = magic
    info.endian = "little" if en == "<" else "big"

    try:
        cputype, _sub, filetype, ncmds, _size, _flags = struct.unpack_from(
            en + "iiIIII", data, 4)
    except struct.error:
        info.warnings.append("truncated Mach-O header")
        return info

    info.arch, info.bits = _CPU.get(cputype & 0xFFFFFFFF,
                                    (Arch.UNKNOWN, 64 if is64 else 32))
    if not info.bits:
        info.bits = 64 if is64 else 32
    info.binary_type = _FILETYPE.get(filetype)

    offset = 32 if is64 else 28
    try:
        _parse_load_commands(data, en, is64, offset, ncmds, info)
    except struct.error as exc:
        info.warnings.append(f"load-command parse failed: {exc}")
    return info


def _parse_fat(data: bytes) -> MachOInfo:
    """Parse a fat/universal binary: pick the preferred slice and analyze it.

    Fat headers are always big-endian. iOS/macOS universal binaries ship this
    way (e.g. arm64 + arm64e, or arm64 + x86_64).
    """
    is64 = data[:4] == _FAT_MAGIC_64
    nfat = struct.unpack_from(">I", data, 4)[0]
    # Sanity bound: a Java .class also starts 0xCAFEBABE; reject absurd counts.
    if not (1 <= nfat <= 64):
        out = MachOInfo()
        out.warnings.append("CAFEBABE header is not a Mach-O fat binary "
                            "(possibly a Java class file)")
        return out

    arch_size = 32 if is64 else 20
    slices: list[tuple[Arch, int, int]] = []  # (arch, offset, size)
    pos = 8
    for _ in range(nfat):
        if pos + arch_size > len(data):
            break
        cputype = struct.unpack_from(">i", data, pos)[0]
        if is64:
            offset, size = struct.unpack_from(">QQ", data, pos + 8)
        else:
            offset, size = struct.unpack_from(">II", data, pos + 8)
        arch, _bits = _CPU.get(cputype & 0xFFFFFFFF, (Arch.UNKNOWN, 0))
        slices.append((arch, offset, size))
        pos += arch_size

    chosen = None
    for pref in _ARCH_PREFERENCE:
        for arch, off, size in slices:
            if arch == pref:
                chosen = (arch, off, size)
                break
        if chosen:
            break
    if chosen is None and slices:
        chosen = slices[0]

    if chosen is None:
        out = MachOInfo(is_fat=True, slice_count=len(slices))
        out.warnings.append("fat binary has no recognizable slices")
        return out

    _arch, off, size = chosen
    slice_bytes = data[off:off + size]
    info = parse_macho(slice_bytes)
    info.is_fat = True
    info.slice_count = len(slices)
    info.warnings.append(
        f"fat binary: {len(slices)} slices "
        f"({', '.join(a.value for a, _, _ in slices)}); analyzed {info.arch.value}")
    return info


def _parse_load_commands(data, en, is64, offset, ncmds, info) -> None:
    from .identify import shannon_entropy

    pos = offset
    for _ in range(min(ncmds, 4096)):
        if pos + 8 > len(data):
            break
        cmd, cmdsize = struct.unpack_from(en + "II", data, pos)
        if cmdsize == 0:
            break
        if cmd in (_LC_SEGMENT, _LC_SEGMENT_64):
            info.sections.extend(_parse_segment(data, en, is64, pos, shannon_entropy))
        elif cmd == _LC_SYMTAB:
            _parse_symtab(data, en, is64, pos, info)
        elif cmd in _DYLIB_COMMANDS:
            _parse_dylib(data, en, pos, cmdsize, info)
        pos += cmdsize


def _parse_dylib(data, en, pos, cmdsize, info) -> None:
    """Read the install name from an LC_LOAD_DYLIB family command."""
    if cmdsize < 12 or pos + 12 > len(data):
        return
    name_offset = struct.unpack_from(en + "I", data, pos + 8)[0]
    if not (0 < name_offset < cmdsize):
        return
    start = pos + name_offset
    end = data.find(b"\x00", start, min(pos + cmdsize, len(data)))
    if end == -1:
        end = min(pos + cmdsize, len(data))
    name = data[start:end].decode("utf-8", "replace")
    if name and name not in info.dylibs:
        info.dylibs.append(name[:512])


def _parse_symtab(data, en, is64, pos, info) -> None:
    """Parse LC_SYMTAB: imported (undefined), exported, and defined functions."""
    symoff, nsyms, stroff, strsize = struct.unpack_from(en + "IIII", data, pos + 8)
    nlist_size = 16 if is64 else 12
    str_end = min(stroff + strsize, len(data))

    def _name(n_strx: int) -> str:
        if n_strx == 0:
            return ""
        start = stroff + n_strx
        if start >= str_end:
            return ""
        end = data.find(b"\x00", start, str_end)
        if end == -1:
            end = str_end
        return data[start:end].decode("utf-8", "replace")

    seen_exp: set[str] = set()
    for i in range(min(nsyms, 200_000)):
        p = symoff + i * nlist_size
        if p + nlist_size > len(data):
            break
        if is64:
            n_strx, n_type, _n_sect, _n_desc, n_value = struct.unpack_from(
                en + "IBBHQ", data, p)
        else:
            n_strx, n_type, _n_sect, _n_desc, n_value = struct.unpack_from(
                en + "IBBHI", data, p)
        if n_type & _N_STAB:  # debug symbol, skip
            continue
        name = _name(n_strx)
        if not name:
            continue
        type_field = n_type & _N_TYPE
        is_ext = n_type & _N_EXT
        if type_field == _N_UNDF:
            if name not in info.dynamic_symbols:
                info.dynamic_symbols.append(name)
        elif type_field == _N_SECT and n_value:
            info.functions.append({"name": name, "address": n_value, "size": 0})
            if is_ext and name not in seen_exp:
                seen_exp.add(name)
                info.exports.append(name)
    info.functions.sort(key=lambda f: f["address"])


def _parse_segments(data, en, is64, offset, ncmds, warnings) -> list[Section]:
    """Back-compat helper: sections only."""
    from .identify import shannon_entropy

    sections: list[Section] = []
    pos = offset
    for _ in range(min(ncmds, 4096)):
        if pos + 8 > len(data):
            break
        cmd, cmdsize = struct.unpack_from(en + "II", data, pos)
        if cmdsize == 0:
            break
        if cmd in (_LC_SEGMENT, _LC_SEGMENT_64):
            sections.extend(_parse_segment(data, en, is64, pos, shannon_entropy))
        pos += cmdsize
    return sections


def _parse_segment(data, en, is64, pos, entropy_fn) -> list[Section]:
    out: list[Section] = []
    if is64:
        nsects = struct.unpack_from(en + "I", data, pos + 64)[0]
        sect_base, sect_size = pos + 72, 80
    else:
        nsects = struct.unpack_from(en + "I", data, pos + 48)[0]
        sect_base, sect_size = pos + 56, 68

    for i in range(min(nsects, 4096)):
        base = sect_base + i * sect_size
        if base + sect_size > len(data):
            break
        sectname = struct.unpack_from("16s", data, base)[0].rstrip(b"\x00").decode("ascii", "replace")
        segname = struct.unpack_from("16s", data, base + 16)[0].rstrip(b"\x00").decode("ascii", "replace")
        if is64:
            addr, size = struct.unpack_from(en + "QQ", data, base + 32)
            off = struct.unpack_from(en + "I", data, base + 48)[0]
        else:
            addr, size = struct.unpack_from(en + "II", data, base + 32)
            off = struct.unpack_from(en + "I", data, base + 40)[0]
        body = data[off:off + size] if size and off else b""
        out.append(Section(
            name=f"{segname},{sectname}",
            virtual_address=addr,
            virtual_size=size,
            raw_size=size,
            raw_offset=off,
            entropy=round(entropy_fn(body), 3) if body else 0.0,
        ))
    return out
