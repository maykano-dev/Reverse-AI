"""Format detection, hashing, and entropy — all stdlib, no dependencies."""

from __future__ import annotations

import hashlib
import math
from collections import Counter

from .models import BinaryFormat

_MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce",  # 32-bit BE
    b"\xce\xfa\xed\xfe",  # 32-bit LE
    b"\xfe\xed\xfa\xcf",  # 64-bit BE
    b"\xcf\xfa\xed\xfe",  # 64-bit LE
    b"\xca\xfe\xba\xbe",  # fat/universal
}


def detect_format(data: bytes) -> BinaryFormat:
    """Identify container format from magic bytes."""
    if len(data) < 4:
        return BinaryFormat.UNKNOWN
    if data[:2] == b"MZ":
        # Could be DOS-only, but PE files start with MZ. Confirm PE header.
        if _pe_signature_present(data):
            return BinaryFormat.PE
        return BinaryFormat.UNKNOWN
    if data[:4] == b"\x7fELF":
        return BinaryFormat.ELF
    if data[:4] in _MACHO_MAGICS:
        return BinaryFormat.MACHO
    return BinaryFormat.UNKNOWN


def _pe_signature_present(data: bytes) -> bool:
    if len(data) < 0x40:
        return False
    e_lfanew = int.from_bytes(data[0x3C:0x40], "little")
    return 0 <= e_lfanew <= len(data) - 4 and data[e_lfanew : e_lfanew + 4] == b"PE\x00\x00"


def compute_hashes(data: bytes) -> dict[str, str]:
    return {
        "md5": hashlib.md5(data).hexdigest(),
        "sha1": hashlib.sha1(data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def shannon_entropy(data: bytes) -> float:
    """Shannon entropy in bits/byte (0.0–8.0). High (>7.0) suggests packing/encryption."""
    if not data:
        return 0.0
    counts = Counter(data)
    length = len(data)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())
