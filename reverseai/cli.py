"""Command-line entry point: `python -m reverseai <command>`."""

from __future__ import annotations

import argparse
import json
import sys

from .core import analyze_file


def _cmd_analyze(args: argparse.Namespace) -> int:
    try:
        report = analyze_file(args.path)
    except FileNotFoundError:
        print(f"error: no such file: {args.path}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    _print_human(report)
    return 0


def _print_human(report) -> None:
    print(f"File:       {report.path}")
    print(f"Size:       {report.size:,} bytes")
    print(f"Format:     {report.fmt.value}")
    print(f"Arch:       {report.arch.value} ({report.bits}-bit, {report.endian}-endian)")
    if report.binary_type:
        print(f"Type:       {report.binary_type}")
    if report.subsystem:
        print(f"Subsystem:  {report.subsystem}")
    if report.entry_point is not None:
        print(f"Entry:      {report.entry_point:#x}")
    print(f"Entropy:    {report.entropy}  (>7.0 suggests packing/encryption)")
    print(f"SHA256:     {report.hashes.get('sha256', '')}")

    if report.sections:
        print(f"\nSections ({len(report.sections)}):")
        print(f"  {'name':<16}{'vaddr':>12}{'vsize':>12}{'raw':>12}  flags  entropy")
        for s in report.sections:
            print(
                f"  {s.name:<16}{s.virtual_address:>12x}{s.virtual_size:>12}"
                f"{s.raw_size:>12}  {s.flags:<5}  {s.entropy}"
            )

    if report.imports:
        total = sum(len(v) for v in report.imports.values())
        print(f"\nImports ({len(report.imports)} libraries, {total} symbols):")
        for lib, syms in report.imports.items():
            preview = ", ".join(syms[:6])
            more = f" … (+{len(syms) - 6})" if len(syms) > 6 else ""
            print(f"  {lib}: {preview}{more}")

    print(f"\nStrings:    {report.string_count} found (showing up to {len(report.strings_sample)})")

    if report.warnings:
        print("\nWarnings:")
        for w in report.warnings:
            print(f"  - {w}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reverseai", description="ReverseAI toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze a binary and print a report")
    analyze.add_argument("path", help="path to the binary file")
    analyze.add_argument("--json", action="store_true", help="emit JSON instead of text")
    analyze.set_defaults(func=_cmd_analyze)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
