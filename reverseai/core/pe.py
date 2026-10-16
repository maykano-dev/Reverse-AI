"""Minimal PE (Portable Executable) parser using only `struct`.

Scope: enough to describe a Windows binary truthfully — machine/arch, bitness,
entry point, subsystem, sections, and imported DLLs/symbols. Full relocation,
exception, and resource parsing is out of scope for this layer.

Every parse step is defensive: a malformed field yields a warning, never a crash.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .models import Arch, Section

# IMAGE_FILE_MACHINE_*
_MACHINE = {
    0x014C: (Arch.X86, 32),
    0x8664: (Arch.X86_64, 64),
    0x01C0: (Arch.ARM, 32),
    0x01C4: (Arch.ARM, 32),  # ARMNT (Thumb-2)
    0xAA64: (Arch.ARM64, 64),
    0x0200: (Arch.UNKNOWN, 64),  # IA64
    0x0166: (Arch.MIPS, 32),
}

_SUBSYSTEM = {
    1: "native",
    2: "windows-gui",
    3: "windows-cui",
    5: "os2-cui",
    7: "posix-cui",
    9: "windows-ce-gui",
    10: "efi-application",
}

# IMAGE_FILE_* characteristics
_FILE_DLL = 0x2000


@dataclass
class PEInfo:
    arch: Arch = Arch.UNKNOWN
    bits: int = 0
    entry_point: int | None = None
    timestamp: int | None = None
    subsystem: str | None = None
    binary_type: str | None = None  # "exe" or "dll"
    sections: list[Section] = field(default_factory=list)
    imports: dict[str, list[str]] = field(default_factory=dict)
    exports: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_pe(data: bytes) -> PEInfo:
    info = PEInfo()
    try:
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        coff = e_lfanew + 4  # skip "PE\0\0"
        (machine, num_sections, timestamp, _ptr_sym, _num_sym,
         size_opt, characteristics) = struct.unpack_from("<HHIIIHH", data, coff)
    except struct.error:
        info.warnings.append("truncated COFF header")
        return info

    info.arch, info.bits = _MACHINE.get(machine, (Arch.UNKNOWN, 0))
    info.timestamp = timestamp
    info.binary_type = "dll" if characteristics & _FILE_DLL else "exe"

    opt = coff + 20
    import_rva = import_size = 0
    export_rva = 0
    try:
        magic = struct.unpack_from("<H", data, opt)[0]
        is_pe32_plus = magic == 0x20B
        if not info.bits:
            info.bits = 64 if is_pe32_plus else 32
        info.entry_point = struct.unpack_from("<I", data, opt + 16)[0]
        info.subsystem = _SUBSYSTEM.get(struct.unpack_from("<H", data, opt + 68)[0])
        # Data directories (8 bytes each): index 0 = export, index 1 = import.
        dd_base = opt + (112 if is_pe32_plus else 96)
        export_rva = struct.unpack_from("<I", data, dd_base + 0)[0]
        import_rva, import_size = struct.unpack_from("<II", data, dd_base + 8)
    except struct.error:
        info.warnings.append("truncated optional header")

    sec_table = opt + size_opt
    info.sections = _parse_sections(data, sec_table, num_sections, info.warnings)

    if import_rva:
        try:
            info.imports = _parse_imports(data, import_rva, info.sections)
        except Exception as exc:  # best-effort; never fatal
            info.warnings.append(f"import parse failed: {exc}")

    if export_rva:
        try:
            info.exports = _parse_exports(data, export_rva, info.sections)
        except Exception as exc:
            info.warnings.append(f"export parse failed: {exc}")

    return info


def _parse_sections(data: bytes, offset: int, count: int, warnings: list[str]) -> list[Section]:
    from .identify import shannon_entropy

    sections: list[Section] = []
    for i in range(count):
        base = offset + i * 40
        if base + 40 > len(data):
            warnings.append(f"section {i} header out of bounds")
            break
        raw_name = struct.unpack_from("<8s", data, base)[0]
        name = raw_name.rstrip(b"\x00").decode("ascii", "replace")
        vsize, vaddr, raw_size, raw_off = struct.unpack_from("<IIII", data, base + 8)
        flags = struct.unpack_from("<I", data, base + 36)[0]
        body = data[raw_off : raw_off + raw_size] if raw_size else b""
        sections.append(
            Section(
                name=name,
                virtual_address=vaddr,
                virtual_size=vsize,
                raw_size=raw_size,
                raw_offset=raw_off,
                entropy=round(shannon_entropy(body), 3),
                flags=_section_flags(flags),
            )
        )
    return sections


def _section_flags(flags: int) -> str:
    out = ""
    if flags & 0x20000000:
        out += "x"
    if flags & 0x40000000:
        out += "r"
    if flags & 0x80000000:
        out += "w"
    return out


def _rva_to_offset(rva: int, sections: list[Section]) -> int | None:
    for s in sections:
        if s.virtual_address <= rva < s.virtual_address + max(s.virtual_size, s.raw_size):
            return s.raw_offset + (rva - s.virtual_address)
    return None


def _read_cstr(data: bytes, offset: int, maxlen: int = 256) -> str:
    end = data.find(b"\x00", offset, offset + maxlen)
    if end == -1:
        end = offset + maxlen
    return data[offset:end].decode("ascii", "replace")


def _parse_imports(data: bytes, import_rva: int, sections: list[Section]) -> dict[str, list[str]]:
    """Walk the import directory: one IMAGE_IMPORT_DESCRIPTOR (20 bytes) per DLL."""
    imports: dict[str, list[str]] = {}
    dir_off = _rva_to_offset(import_rva, sections)
    if dir_off is None:
        return imports

    idx = 0
    while True:
        base = dir_off + idx * 20
        if base + 20 > len(data):
            break
        desc = struct.unpack_from("<IIIII", data, base)
        orig_first_thunk, _ts, _fwd, name_rva, first_thunk = desc
        if desc == (0, 0, 0, 0, 0):
            break  # terminator
        name_off = _rva_to_offset(name_rva, sections)
        dll = _read_cstr(data, name_off) if name_off is not None else f"<rva:{name_rva:#x}>"
        imports[dll] = _parse_thunks(data, orig_first_thunk or first_thunk, sections)
        idx += 1
        if idx > 4096:  # sanity bound
            break
    return imports


def _parse_exports(data: bytes, export_rva: int, sections: list[Section]) -> list[str]:
    """Read exported symbol names from the export directory (names only)."""
    dir_off = _rva_to_offset(export_rva, sections)
    if dir_off is None or dir_off + 40 > len(data):
        return []
    # IMAGE_EXPORT_DIRECTORY: NumberOfNames at +24, AddressOfNames (RVA) at +32
    num_names = struct.unpack_from("<I", data, dir_off + 24)[0]
    names_rva = struct.unpack_from("<I", data, dir_off + 32)[0]
    names_off = _rva_to_offset(names_rva, sections)
    if names_off is None:
        return []
    out: list[str] = []
    for i in range(min(num_names, 8192)):
        pos = names_off + i * 4
        if pos + 4 > len(data):
            break
        name_rva = struct.unpack_from("<I", data, pos)[0]
        name_off = _rva_to_offset(name_rva, sections)
        if name_off is not None:
            out.append(_read_cstr(data, name_off))
    return out


def _parse_thunks(data: bytes, thunk_rva: int, sections: list[Section]) -> list[str]:
    """Read imported symbol names from a thunk array (assumes 64-bit thunks; falls back to 32)."""
    symbols: list[str] = []
    if not thunk_rva:
        return symbols
    thunk_off = _rva_to_offset(thunk_rva, sections)
    if thunk_off is None:
        return symbols

    # Heuristic: try 8-byte thunks (PE32+), then 4-byte (PE32).
    for size, fmt, ord_flag in ((8, "<Q", 1 << 63), (4, "<I", 1 << 31)):
        syms: list[str] = []
        i = 0
        ok = True
        while i < 8192:
            pos = thunk_off + i * size
            if pos + size > len(data):
                break
            val = struct.unpack_from(fmt, data, pos)[0]
            if val == 0:
                break
            if val & ord_flag:
                syms.append(f"#ordinal_{val & 0xFFFF}")
            else:
                name_off = _rva_to_offset(val & 0x7FFFFFFF, sections)
                if name_off is None:
                    ok = False
                    break
                # IMAGE_IMPORT_BY_NAME: 2-byte hint, then name
                syms.append(_read_cstr(data, name_off + 2))
            i += 1
        if ok and syms:
            return syms
    return symbols
