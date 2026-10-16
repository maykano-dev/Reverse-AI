"""Command-line entry point: `python -m reverseai <command>`.

Commands:
  analyze <file>            static analysis report
  caps                      show host sandbox/analysis capabilities
  sandbox run -- <argv...>  run a command in the hardened sandbox
  agent run --goal ...      run an autonomous investigation
"""

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
    _print_analysis(report)
    return 0


def _print_analysis(report) -> None:
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
            print(f"  {s.name:<16}{s.virtual_address:>12x}{s.virtual_size:>12}"
                  f"{s.raw_size:>12}  {s.flags:<5}  {s.entropy}")

    if report.imports:
        total = sum(len(v) for v in report.imports.values())
        print(f"\nImports ({len(report.imports)} libraries, {total} symbols):")
        for lib, syms in report.imports.items():
            preview = ", ".join(syms[:6])
            more = f" … (+{len(syms) - 6})" if len(syms) > 6 else ""
            print(f"  {lib}: {preview}{more}")

    if report.needed_libraries and not report.imports:
        print(f"\nNeeded libraries ({len(report.needed_libraries)}):")
        for lib in report.needed_libraries:
            print(f"  {lib}")
    if report.dynamic_symbols:
        preview = ", ".join(report.dynamic_symbols[:10])
        print(f"\nImported symbols ({len(report.dynamic_symbols)}): {preview} …")
    if report.exports:
        preview = ", ".join(report.exports[:10])
        print(f"\nExports ({len(report.exports)}): {preview}"
              f"{' …' if len(report.exports) > 10 else ''}")

    print(f"\nStrings:    {report.string_count} found (showing up to {len(report.strings_sample)})")
    if report.warnings:
        print("\nWarnings:")
        for w in report.warnings:
            print(f"  - {w}")


def _cmd_diff(args: argparse.Namespace) -> int:
    from .core.diff import diff_files

    try:
        d = diff_files(args.a, args.b)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(d.to_dict(), indent=2))
        return 0
    print(f"Summary: {d.summary}")
    print(f"identical={d.identical} same_format={d.same_format} same_arch={d.same_arch}")
    print(f"size delta: {d.size_delta:+d} bytes   entropy delta: {d.entropy_delta:+.3f}")
    for label, vals in [
        ("sections +", d.sections_added), ("sections -", d.sections_removed),
        ("imports +", d.imports_added), ("imports -", d.imports_removed),
        ("exports +", d.exports_added), ("exports -", d.exports_removed),
        ("needed +", d.needed_added), ("needed -", d.needed_removed),
    ]:
        if vals:
            print(f"  {label}: {', '.join(vals[:12])}{' …' if len(vals) > 12 else ''}")
    for ch in d.sections_changed:
        print(f"  section changed: {ch['name']} raw_size {ch['raw_size']} "
              f"entropy {ch['entropy']} flags {ch['flags']}")
    return 0


def _cmd_caps(args: argparse.Namespace) -> int:
    from .sandbox import detect_capabilities

    caps = detect_capabilities()
    if args.json:
        print(json.dumps(caps.to_dict(), indent=2))
        return 0
    print(f"Best isolation:    {caps.best_isolation()}")
    print(f"Can run untrusted: {caps.can_run_untrusted()}")
    print("\nDetails:")
    for k, v in caps.to_dict().items():
        mark = "✓" if v else "·"
        print(f"  {mark} {k}: {v}")
    return 0


def _cmd_sandbox_run(args: argparse.Namespace) -> int:
    from .sandbox import SandboxPolicy, SandboxUnavailable, create_sandbox

    if not args.argv:
        print("error: provide a command after --", file=sys.stderr)
        return 2
    policy = SandboxPolicy(
        allow_network=args.network,
        allow_untrusted_execution=args.untrusted,
        timeout_seconds=args.timeout,
        ro_binds=args.ro_bind or [],
    )
    try:
        sb = create_sandbox(policy)
    except SandboxUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    res = sb.run(list(args.argv), policy)
    if args.json:
        print(json.dumps(res.to_dict(), indent=2))
        return 0 if res.ok else 1
    iso = res.isolation
    print(f"backend: {iso.backend} (level {iso.level}) "
          f"net_blocked={iso.network_blocked} fs={iso.filesystem}")
    print(f"exit={res.exit_code} signal={res.term_signal} timed_out={res.timed_out} "
          f"({res.duration_s:.3f}s)")
    if res.stdout:
        print("--- stdout ---")
        print(res.stdout_text())
    if res.stderr:
        print("--- stderr ---", file=sys.stderr)
        print(res.stderr_text(), file=sys.stderr)
    if res.error:
        print(f"error: {res.error}", file=sys.stderr)
    return 0 if res.ok else 1


def _cmd_agent_run(args: argparse.Namespace) -> int:
    from .agent import Agent, Permission, get_provider
    from .agent.providers.deepseek import ProviderError

    perm = {"read": Permission.READ, "execute": Permission.EXECUTE,
            "write": Permission.WRITE}[args.permission]
    try:
        provider = get_provider(args.provider)
    except (ProviderError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    agent = Agent(provider, max_permission=perm, max_steps=args.max_steps)
    job = agent.run(args.goal, target_path=args.target, project_dir=args.project_dir)

    print(job.report())
    print(f"\n[usage] {job.usage}  steps={job.steps}  status={job.status}")
    if args.save:
        path = job.save(args.save)
        print(f"[saved] {path}")
    return 0 if job.status == "completed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reverseai", description="ReverseAI toolkit")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="static analysis report for a binary")
    analyze.add_argument("path")
    analyze.add_argument("--json", action="store_true")
    analyze.set_defaults(func=_cmd_analyze)

    caps = sub.add_parser("caps", help="show host sandbox/analysis capabilities")
    caps.add_argument("--json", action="store_true")
    caps.set_defaults(func=_cmd_caps)

    diff = sub.add_parser("diff", help="structural diff between two binaries")
    diff.add_argument("a")
    diff.add_argument("b")
    diff.add_argument("--json", action="store_true")
    diff.set_defaults(func=_cmd_diff)

    sbx = sub.add_parser("sandbox", help="sandbox operations")
    sbx_sub = sbx.add_subparsers(dest="sandbox_cmd", required=True)
    sbx_run = sbx_sub.add_parser("run", help="run a command in the hardened sandbox")
    sbx_run.add_argument("--network", action="store_true", help="allow network (default off)")
    sbx_run.add_argument("--untrusted", action="store_true",
                         help="treat as untrusted (require isolating backend)")
    sbx_run.add_argument("--timeout", type=float, default=10.0)
    sbx_run.add_argument("--ro-bind", action="append", metavar="PATH",
                         help="expose a host path read-only (repeatable)")
    sbx_run.add_argument("--json", action="store_true")
    sbx_run.add_argument("argv", nargs=argparse.REMAINDER,
                         help="-- then the command to run")
    sbx_run.set_defaults(func=_cmd_sandbox_run)

    agent = sub.add_parser("agent", help="autonomous investigation agent")
    agent_sub = agent.add_subparsers(dest="agent_cmd", required=True)
    agent_run = agent_sub.add_parser("run", help="run an investigation")
    agent_run.add_argument("--goal", required=True)
    agent_run.add_argument("--target", help="path to the target binary")
    agent_run.add_argument("--project-dir", dest="project_dir",
                           help="project directory for coding tasks")
    agent_run.add_argument("--provider", default="deepseek",
                           help="llm provider (deepseek|mock)")
    agent_run.add_argument("--permission", default="execute",
                           choices=["read", "execute", "write"])
    agent_run.add_argument("--max-steps", type=int, default=24, dest="max_steps")
    agent_run.add_argument("--save", metavar="DIR", help="save the job record JSON here")
    agent_run.set_defaults(func=_cmd_agent_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # strip a leading "--" from sandbox REMAINDER
    if getattr(args, "argv", None) and args.argv and args.argv[0] == "--":
        args.argv = args.argv[1:]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
