"""Top-level analysis: file in, structured AnalysisReport out."""

from __future__ import annotations

from pathlib import Path

from . import elf, pe
from .identify import compute_hashes, detect_format, shannon_entropy
from .models import AnalysisReport, BinaryFormat
from .strings import extract_strings

STRINGS_SAMPLE_LIMIT = 200


def analyze_bytes(data: bytes, path: str = "<memory>") -> AnalysisReport:
    report = AnalysisReport(
        path=path,
        size=len(data),
        fmt=detect_format(data),
        hashes=compute_hashes(data),
        entropy=round(shannon_entropy(data), 3),
    )

    if report.fmt is BinaryFormat.PE:
        info = pe.parse_pe(data)
        report.arch = info.arch
        report.bits = info.bits
        report.entry_point = info.entry_point
        report.timestamp = info.timestamp
        report.subsystem = info.subsystem
        report.binary_type = info.binary_type
        report.sections = info.sections
        report.imports = info.imports
        report.exports = info.exports
        report.needed_libraries = list(info.imports.keys())
        report.warnings.extend(info.warnings)
    elif report.fmt is BinaryFormat.ELF:
        info = elf.parse_elf(data)
        report.arch = info.arch
        report.bits = info.bits
        report.endian = info.endian
        report.entry_point = info.entry_point
        report.binary_type = info.binary_type
        report.sections = info.sections
        report.needed_libraries = info.needed_libraries
        report.dynamic_symbols = info.dynamic_symbols
        report.exports = info.exports
        report.warnings.extend(info.warnings)

    all_strings = extract_strings(data, min_len=5)
    report.string_count = len(all_strings)
    report.strings_sample = all_strings[:STRINGS_SAMPLE_LIMIT]

    return report


def analyze_file(path: str | Path) -> AnalysisReport:
    p = Path(path)
    data = p.read_bytes()
    report = analyze_bytes(data, path=str(p))
    return report
