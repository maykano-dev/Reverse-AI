"""Android APK analysis (ZIP-based, stdlib only)."""

from __future__ import annotations

import re
import zipfile
from dataclasses import asdict, dataclass, field
from typing import Any

from ..core import elf
from ..core.strings import extract_strings

_PACKAGE_RE = re.compile(r"\b([a-z][a-z0-9_]*(?:\.[a-z0-9_]+){2,})\b")
_PERM_RE = re.compile(r"android\.permission\.[A-Z_]+")


@dataclass
class NativeLib:
    name: str
    arch: str
    bits: int
    imports: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class APKReport:
    is_apk: bool = False
    package: str | None = None
    permissions: list[str] = field(default_factory=list)
    dex_files: list[str] = field(default_factory=list)
    native_libs: list[NativeLib] = field(default_factory=list)
    abis: list[str] = field(default_factory=list)
    asset_count: int = 0
    resource_count: int = 0
    file_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["native_libs"] = [n.to_dict() for n in self.native_libs]
        return d


def is_apk(path: str) -> bool:
    try:
        if not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
        return "AndroidManifest.xml" in names and any(
            n.endswith(".dex") for n in names)
    except (OSError, zipfile.BadZipFile):
        return False


def analyze_apk(path: str, max_native: int = 12) -> APKReport:
    report = APKReport()
    if not zipfile.is_zipfile(path):
        report.warnings.append("not a zip/APK")
        return report

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        report.file_count = len(names)
        report.is_apk = "AndroidManifest.xml" in names and any(
            n.endswith(".dex") for n in names)
        report.dex_files = sorted(n for n in names if n.endswith(".dex"))
        report.asset_count = sum(1 for n in names if n.startswith("assets/"))
        report.resource_count = sum(1 for n in names if n.startswith("res/"))

        abis = set()
        for n in names:
            if n.startswith("lib/") and n.endswith(".so"):
                parts = n.split("/")
                if len(parts) >= 3:
                    abis.add(parts[1])
        report.abis = sorted(abis)

        # Package + permissions from the (binary) AndroidManifest string pool.
        if "AndroidManifest.xml" in names:
            try:
                data = z.read("AndroidManifest.xml")
                report.package, report.permissions = _manifest_hints(data)
            except (KeyError, OSError) as exc:
                report.warnings.append(f"manifest read failed: {exc}")

        # Analyze bundled native libraries as ELF binaries.
        libs = [n for n in names if n.startswith("lib/") and n.endswith(".so")]
        for n in libs[:max_native]:
            try:
                info = elf.parse_elf(z.read(n))
                report.native_libs.append(NativeLib(
                    name=n, arch=info.arch.value, bits=info.bits,
                    imports=len(info.dynamic_symbols)))
            except (KeyError, OSError, Exception):
                continue
    return report


def _manifest_hints(data: bytes) -> tuple[str | None, list[str]]:
    """Pull package name + permissions from the binary manifest's string pool."""
    strings = extract_strings(data, min_len=5)
    perms = sorted({m.group(0) for s in strings for m in _PERM_RE.finditer(s)})
    pkg = None
    for s in strings:
        m = _PACKAGE_RE.search(s)
        if m and not m.group(1).startswith("android.") and "permission" not in m.group(1):
            pkg = m.group(1)
            break
    return pkg, perms
