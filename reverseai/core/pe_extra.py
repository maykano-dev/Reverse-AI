"""Additional PE structures: resources, version info, debug, TLS, rich header.

All parsing is defensive and bounded. Missing or malformed directories produce a
warning, never a crash. This is still not a full resource editor; it is a truthful
inventory for analysis and planning.
"""

from __future__ import annotations

import struct
from typing import Any

from .pe import PEInfo, _read_cstr, _rva_to_offset


def _dd(data: bytes, opt: int, is_pe32_plus: bool, index: int) -> tuple[int, int]:
    base = opt + (112 if is_pe32_plus else 96) + index * 8
    try:
        return struct.unpack_from("<II", data, base)
    except struct.error:
        return 0, 0


def _image_base(data: bytes, opt: int, is_pe32_plus: bool) -> int:
    try:
        return struct.unpack_from("<Q" if is_pe32_plus else "<I",
                                  data, opt + (24 if is_pe32_plus else 28))[0]
    except struct.error:
        return 0


def _rich_header(data: bytes, e_lfanew: int) -> dict[str, Any]:
    end = min(e_lfanew, len(data))
    pos = data.rfind(b"Rich", 0, end)
    if pos < 0 or pos + 8 > len(data):
        return {}
    key = struct.unpack_from("<I", data, pos + 4)[0]
    # Walk backwards in 4-byte words until the XORed "DanS" marker.
    words = []
    cursor = pos
    while cursor - 4 >= 0 and len(words) < 256:
        cursor -= 4
        words.append(struct.unpack_from("<I", data, cursor)[0] ^ key)
        if words[-1] == 0x536E6144:  # "DanS"
            break
    if not words or words[-1] != 0x536E6144:
        return {"key": f"{key:#x}", "entries": []}
    entries = []
    # words is reversed; drop DanS + 3 padding words.
    body = list(reversed(words[:-4]))
    for i in range(0, len(body) - 1, 2):
        entries.append({"id": body[i], "count": body[i + 1]})
    return {"key": f"{key:#x}", "entries": entries[:80]}


def _debug_directory(data: bytes, sections, rva: int, size: int) -> list[dict[str, Any]]:
    off = _rva_to_offset(rva, sections)
    if off is None:
        return []
    out = []
    for i in range(min(size // 28, 16)):
        base = off + i * 28
        if base + 28 > len(data):
            break
        (_chars, _ts, _maj, _min, dtype, data_size, data_rva,
         data_ptr) = struct.unpack_from("<IIHHIIII", data, base)
        row = {"type": dtype, "size": data_size, "rva": data_rva,
               "pointer": data_ptr}
        if dtype == 2 and data_ptr and data_ptr + 4 <= len(data):
            if data[data_ptr:data_ptr + 4] == b"RSDS":
                guid = data[data_ptr + 4:data_ptr + 20].hex()
                age = struct.unpack_from("<I", data, data_ptr + 20)[0] \
                    if data_ptr + 24 <= len(data) else 0
                path = _read_cstr(data, data_ptr + 24, 512)
                row.update({"guid": guid, "age": age, "pdb": path})
        out.append(row)
    return out


def _tls(data: bytes, sections, rva: int, size: int, image_base: int,
         is_pe32_plus: bool) -> dict[str, Any]:
    off = _rva_to_offset(rva, sections)
    if off is None or off + (40 if is_pe32_plus else 24) > len(data):
        return {}
    if is_pe32_plus:
        (_start, _end, _index, callbacks_va) = struct.unpack_from("<QQQQ", data, off)
        ptr_size, fmt = 8, "<Q"
    else:
        (_start, _end, _index, callbacks_va) = struct.unpack_from("<IIII", data, off)
        ptr_size, fmt = 4, "<I"
    callbacks = []
    if callbacks_va and image_base:
        cb_rva = callbacks_va - image_base
        cb_off = _rva_to_offset(cb_rva, sections)
        if cb_off is not None:
            for i in range(64):
                pos = cb_off + i * ptr_size
                if pos + ptr_size > len(data):
                    break
                value = struct.unpack_from(fmt, data, pos)[0]
                if value == 0:
                    break
                callbacks.append(value)
    return {"callbacks": callbacks, "callback_count": len(callbacks)}


def _resource_tree(data: bytes, sections, root_rva: int) -> tuple[list[dict[str, Any]], list[str]]:
    root_off = _rva_to_offset(root_rva, sections)
    if root_off is None:
        return [], ["resource directory is not mapped"]
    entries: list[dict[str, Any]] = []
    versions: list[str] = []

    def walk(off: int, depth: int, path: list[Any]) -> None:
        if depth > 4 or off + 16 > len(data):
            return
        named, ids = struct.unpack_from("<HH", data, off + 12)
        count = named + ids
        for i in range(min(count, 512)):
            entry = off + 16 + i * 8
            if entry + 8 > len(data):
                break
            name_field, data_field = struct.unpack_from("<II", data, entry)
            label: Any = name_field & 0x7FFFFFFF
            if name_field & 0x80000000:
                name_off = root_off + (name_field & 0x7FFFFFFF)
                label = _read_cstr(data, name_off, 128)
            if data_field & 0x80000000:
                walk(root_off + (data_field & 0x7FFFFFFF), depth + 1,
                     path + [label])
                continue
            leaf = root_off + data_field
            if leaf + 16 > len(data):
                continue
            data_rva, size, _cp, _res = struct.unpack_from("<IIII", data, leaf)
            body_off = _rva_to_offset(data_rva, sections)
            body = data[body_off:body_off + min(size, 4096)] if body_off else b""
            preview = body[:120].hex()
            entries.append({
                "path": path + [label], "type": path[0] if path else label,
                "name": path[1] if len(path) > 1 else "",
                "language": label, "size": size, "rva": data_rva,
                "preview_hex": preview,
            })
            if path and path[0] == 16:  # RT_VERSION
                try:
                    text = body.decode("utf-16-le", "ignore")
                    for part in text.replace("\x00", "\n").splitlines():
                        part = part.strip()
                        if 2 <= len(part) <= 120 and any(c.isalpha() for c in part):
                            versions.append(part)
                except Exception:
                    pass

    walk(root_off, 0, [])
    return entries[:200], versions[:40]


def parse_pe_extra(data: bytes, info: PEInfo | None = None) -> dict[str, Any]:
    try:
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        coff = e_lfanew + 4
        opt = coff + 20
        magic = struct.unpack_from("<H", data, opt)[0]
        is_pe32_plus = magic == 0x20B
        sections = info.sections if info is not None else []
        image_base = _image_base(data, opt, is_pe32_plus)
        out: dict[str, Any] = {
            "rich_header": _rich_header(data, e_lfanew),
            "resources": [], "version_strings": [],
            "debug": [], "tls": {},
        }
        rsrc_rva, rsrc_size = _dd(data, opt, is_pe32_plus, 2)
        if rsrc_rva:
            resources, versions = _resource_tree(data, sections, rsrc_rva)
            out["resources"] = resources
            out["version_strings"] = versions
        dbg_rva, dbg_size = _dd(data, opt, is_pe32_plus, 6)
        if dbg_rva:
            out["debug"] = _debug_directory(data, sections, dbg_rva, dbg_size)
        tls_rva, tls_size = _dd(data, opt, is_pe32_plus, 9)
        if tls_rva:
            out["tls"] = _tls(data, sections, tls_rva, tls_size,
                              image_base, is_pe32_plus)
        return out
    except (struct.error, ValueError, OSError) as exc:
        return {"warnings": [f"PE extra parse failed: {exc}"],
                "resources": [], "version_strings": [], "debug": [], "tls": {},
                "rich_header": {}}
