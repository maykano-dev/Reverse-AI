"""Command-line entry point: `python -m reverseai <command>`.

Commands:
  analyze <file>            static analysis report
  world <file>              build a world model for a target
  discover <file>           propose evidence-backed opportunities
  caps                      show host sandbox/analysis capabilities
  readiness <file>          can this target be executed and verified here?
  sandbox run -- <argv...>  run a command in the hardened sandbox
  verify                    signed behavioral verification without a model
  corpus                    capture/list/replay durable behavioral corpora
  report                    verify or render a signed report
  agent run --goal ...      run an autonomous investigation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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


def _cmd_cfg(args: argparse.Namespace) -> int:
    from .core.cfg import analyze_control_flow

    try:
        flow = analyze_control_flow(args.path, max_functions=args.functions)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(flow.to_dict(), indent=2))
        return 0
    print(f"functions: {len(flow.functions)}  blocks: "
          f"{sum(len(f.blocks) for f in flow.functions)}  calls: "
          f"{sum(len(f.calls) for f in flow.functions)}")
    for f in flow.functions:
        print(f"  {f.name} @ 0x{f.address:x}: {len(f.blocks)} blocks, "
              f"{f.edges} edges, complexity {f.cyclomatic_complexity}")
        for b in f.blocks[:args.show_blocks]:
            succ = ", ".join(f"0x{s:x}" for s in b.successors) or "none"
            print(f"    0x{b.address:x} .. 0x{b.end:x}  {b.terminator}  -> {succ}")
    if flow.warnings:
        print("warnings: " + "; ".join(flow.warnings))
    return 0


def _cmd_approvals(args: argparse.Namespace) -> int:
    import os
    from .security.approvals import ApprovalError, ApprovalLedger

    base = os.environ.get("REVERSEAI_STORE", "").strip()
    directory = args.dir or (str(Path(base) / "approvals") if base else None)
    ledger = ApprovalLedger(directory)
    if args.approvals_cmd == "list":
        rows = ledger.pending()
        if args.json:
            print(json.dumps(rows, indent=2))
        elif not rows:
            print("No live approvals.")
        else:
            for row in rows:
                print(f"{row['id']}  {row['action']}  scope={row['scope']!r}  "
                      f"uses={row.get('uses', 0)}/{row.get('max_uses', 1)}  "
                      f"expires={row.get('expires_at')}")
        return 0
    if args.approvals_cmd == "grant":
        try:
            grant = ledger.grant(args.action, args.scope, args.reason,
                                 ttl_seconds=args.ttl,
                                 max_uses=args.max_uses)
        except ApprovalError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(grant.to_dict(), indent=2))
        else:
            print(grant.token)
            print(f"action={grant.approval.action} scope={grant.approval.scope!r} "
                  f"expires_in={int(args.ttl)}s uses={grant.approval.max_uses}",
                  file=sys.stderr)
        return 0
    return 2


def _cmd_world(args: argparse.Namespace) -> int:
    from .intelligence.world import world_from_analysis

    try:
        report = analyze_file(args.path)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    wm = world_from_analysis(report)
    if args.json:
        print(json.dumps(wm.to_dict(), indent=2))
    else:
        print(json.dumps(wm.summary(), indent=2))
        if args.unresolved:
            for row in wm.unresolved()[:args.limit]:
                print(f"- {row['type']}: {row['name']} ({row['confidence']})")
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    from .intelligence.discovery import DiscoveryEngine
    from .intelligence.world import world_from_analysis

    try:
        report = analyze_file(args.path)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    wm = world_from_analysis(report)
    engine = DiscoveryEngine(wm)
    opps = engine.discover(report, corpus_present=args.corpus,
                           tests_present=args.tests)
    if args.json:
        print(json.dumps({
            "summary": engine.summary(),
            "opportunities": [o.to_dict() for o in opps],
            "hypotheses": [h.to_dict() for h in engine.hypotheses()],
            "mission": engine.mission(max_steps=args.steps,
                                      max_effort=args.effort),
        }, indent=2))
        return 0
    print(f"{len(opps)} opportunity(ies) for {args.path}")
    for o in opps[:args.limit]:
        approval = " [approval]" if o.requires_approval else ""
        print(f"\n[{o.category}] {o.title}{approval}")
        print(f"  confidence: {o.confidence}  score: {o.score}  "
              f"impact/effort/risk: {o.impact}/{o.effort}/{o.risk}")
        print(f"  next: {o.proposed_action}")
    print("\nThis is a plan, not permission to modify the system.")
    return 0


def _cmd_capabilities(args: argparse.Namespace) -> int:
    from .security.capabilities import CapabilityPolicy

    status = CapabilityPolicy().status()
    if args.json:
        print(json.dumps(status, indent=2))
        return 0
    for name, row in status.items():
        mark = "on " if row.get("allowed") else "off"
        print(f"  [{mark}] {name:<20} risk={row.get('risk')}  {row.get('reason')}")
    return 0


def _cmd_readiness(args: argparse.Namespace) -> int:
    from .sandbox.readiness import assess_execution
    from .sandbox import SandboxPolicy

    policy = SandboxPolicy(allow_untrusted_execution=True,
                           timeout_seconds=args.timeout)
    result = assess_execution(args.path, policy)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return 0 if result.verdict in ("executable", "emulated") else 1
    print(f"Target:     {result.target}")
    print(f"Format:     {result.format}")
    print(f"Arch:       {result.arch}")
    print(f"Host:       {result.host_os}/{result.host_arch}")
    print(f"Backend:    {result.backend} (level {result.level})")
    print(f"Verdict:    {result.verdict}")
    print(f"Reason:     {result.reason}")
    if result.suggestions:
        print("Next:")
        for s in result.suggestions:
            print(f"  - {s}")
    return 0 if result.verdict in ("executable", "emulated") else 1


def _cmd_verify(args: argparse.Namespace) -> int:
    from .sandbox import SandboxPolicy
    from .verify.replay import (
        ReplayError, load_cases, replay_record, write_reports,
    )

    try:
        cases = load_cases(args.cases)
    except ReplayError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    policy = SandboxPolicy(allow_untrusted_execution=True,
                           timeout_seconds=args.timeout)
    record = replay_record(
        args.original, args.modified, cases,
        goal=args.goal or "",
        policy=policy,
        output_files=args.output_file or [],
        timeout_seconds=args.timeout,
    )
    verification = record["verification"]
    if args.report:
        try:
            write_reports(record, args.report)
        except OSError as exc:
            print(f"error: could not write report: {exc}", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print(f"verified: {verification['verified']}")
        print(f"reason:   {verification['reason']}")
        print(f"tests:    {verification['passed_tests']} passed / "
              f"{verification['tests_run']} run")
        if verification.get("test_summary", {}).get("unexpected"):
            print("unexpected: "
                  + ", ".join(verification["test_summary"]["unexpected"]))
        if args.report:
            print(f"report:   {args.report}")
    return 0 if verification["verified"] else 1


def _cmd_corpus(args: argparse.Namespace) -> int:
    from .verify.corpus import (
        CorpusError, CorpusStore, capture_corpus, default_corpus_dir,
        target_sha256,
    )
    from .verify.difftest import generate_corpus
    from .verify.replay import load_cases

    directory = args.dir or str(default_corpus_dir())
    store = CorpusStore(directory)
    if args.corpus_cmd == "list":
        rows = store.list()
        if args.json:
            print(json.dumps(rows, indent=2))
        elif not rows:
            print("No corpora yet.")
        else:
            for r in rows:
                print(f"{r['target_sha256'][:12]}  {r['cases']:>3} cases  "
                      f"{r.get('goal', '')[:60]}")
        return 0
    if args.corpus_cmd == "show":
        try:
            cases = store.load(args.sha)
        except CorpusError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps([c.to_dict() for c in cases], indent=2))
        else:
            for c in cases:
                print(f"{c.name}: args={c.args} expect={c.expect}")
        return 0 if cases else 1
    if args.corpus_cmd == "capture":
        try:
            cases = load_cases(args.cases) if args.cases else generate_corpus()
            captured, summary = capture_corpus(
                args.target, cases,
                output_files=args.output_file or [],
                timeout_seconds=args.timeout,
            )
            sha = target_sha256(args.target)
            path = store.save(sha, captured, goal=args.goal or "capture")
        except (CorpusError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps({
                "target_sha256": sha, "cases": len(captured),
                "path": str(path), "summary": summary,
            }, indent=2))
        else:
            print(f"captured {len(captured)} case(s) for {sha[:12]}")
            print(f"stored: {path}")
            print(summary.get("summary", ""))
        return 0
    return 2


def _cmd_report(args: argparse.Namespace) -> int:
    from .verify.report import render_html, render_json, verify_signature

    try:
        with open(args.path, "r", encoding="utf-8") as fh:
            report = json.loads(fh.read())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not isinstance(report, dict):
        print("error: report must be a JSON object", file=sys.stderr)
        return 2
    if args.report_cmd == "verify":
        ok = verify_signature(report)
        if args.json:
            print(json.dumps({"valid": ok, "algorithm": report.get("algorithm"),
                              "tier": report.get("evidence_tier")}, indent=2))
        else:
            print(f"signature: {'valid' if ok else 'INVALID'} "
                  f"({report.get('algorithm')})")
            print(f"tier:      {report.get('evidence_tier')}")
            print(f"delivery:  {report.get('delivery', {}).get('allowed')}")
        return 0 if ok else 1
    if args.report_cmd == "render":
        if args.html:
            print(render_html(report))
        else:
            print(render_json(report))
        return 0
    return 2


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


def _cmd_bench(args: argparse.Namespace) -> int:
    from .agent import Agent, Permission, get_provider
    from .agent.providers.deepseek import ProviderError
    from .bench import builtin_tasks, run_suite

    try:
        get_provider(args.provider)  # fail fast on missing config
    except (ProviderError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    def factory(perm):
        return Agent(get_provider(args.provider), max_permission=perm,
                     max_steps=args.max_steps)

    tasks = builtin_tasks()
    if args.only:
        tasks = [t for t in tasks if t.id in set(args.only)]
    report = run_suite(factory, tasks)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.render())
    return 0 if report.passed == report.total else 1


def _cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    serve(host=args.host, port=args.port, store_dir=args.store)
    return 0


def _cmd_agent_run(args: argparse.Namespace) -> int:
    import os
    from pathlib import Path

    from .agent import Agent, Permission, get_provider
    from .agent.memory import MemoryStore, default_memory_path
    from .agent.skills import load_skills
    from .agent.providers.deepseek import ProviderError

    perm = {"read": Permission.READ, "execute": Permission.EXECUTE,
            "write": Permission.WRITE}[args.permission]
    try:
        provider = get_provider(args.provider)
    except (ProviderError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    skills_root = os.environ.get("REVERSEAI_SKILLS")
    agent = Agent(
        provider, max_permission=perm, max_steps=args.max_steps,
        template=getattr(args, "template", "general"),
        memory=MemoryStore(default_memory_path()),
        skills=load_skills(Path(skills_root) if skills_root else None),
        mode=getattr(args, "mode", ""),
    )
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

    world = sub.add_parser("world", help="build a world model for a target")
    world.add_argument("path")
    world.add_argument("--json", action="store_true")
    world.add_argument("--unresolved", action="store_true")
    world.add_argument("--limit", type=int, default=20)
    world.set_defaults(func=_cmd_world)

    discover = sub.add_parser("discover",
                              help="propose evidence-backed opportunities")
    discover.add_argument("path")
    discover.add_argument("--json", action="store_true")
    discover.add_argument("--corpus", action="store_true",
                          help="a behavioral corpus already exists")
    discover.add_argument("--tests", action="store_true",
                          help="acceptance tests already exist")
    discover.add_argument("--steps", type=int, default=6)
    discover.add_argument("--effort", type=int, default=15)
    discover.add_argument("--limit", type=int, default=12)
    discover.set_defaults(func=_cmd_discover)

    capabilities = sub.add_parser("capabilities",
                                  help="show the high-risk capability policy")
    capabilities.add_argument("--json", action="store_true")
    capabilities.set_defaults(func=_cmd_capabilities)

    approvals = sub.add_parser("approvals",
                               help="issue or list short-lived action approvals")
    approvals_sub = approvals.add_subparsers(dest="approvals_cmd", required=True)
    appr_grant = approvals_sub.add_parser("grant", help="issue a scoped approval")
    appr_grant.add_argument("--action", required=True)
    appr_grant.add_argument("--scope", default="")
    appr_grant.add_argument("--reason", default="")
    appr_grant.add_argument("--ttl", type=float, default=300.0)
    appr_grant.add_argument("--max-uses", dest="max_uses", type=int, default=1)
    appr_grant.add_argument("--dir")
    appr_grant.add_argument("--json", action="store_true")
    appr_grant.set_defaults(func=_cmd_approvals)
    appr_list = approvals_sub.add_parser("list", help="list live approvals")
    appr_list.add_argument("--dir")
    appr_list.add_argument("--json", action="store_true")
    appr_list.set_defaults(func=_cmd_approvals)

    cfg = sub.add_parser("cfg", help="bounded control-flow and call graph")
    cfg.add_argument("path")
    cfg.add_argument("--functions", type=int, default=12)
    cfg.add_argument("--show-blocks", dest="show_blocks", type=int, default=12)
    cfg.add_argument("--json", action="store_true")
    cfg.set_defaults(func=_cmd_cfg)

    readiness = sub.add_parser("readiness",
                               help="can this target be executed and verified here?")
    readiness.add_argument("path")
    readiness.add_argument("--timeout", type=float, default=10.0)
    readiness.add_argument("--json", action="store_true")
    readiness.set_defaults(func=_cmd_readiness)

    verify = sub.add_parser("verify",
                            help="signed behavioral verification without a model")
    verify.add_argument("--original", required=True)
    verify.add_argument("--modified", required=True)
    verify.add_argument("--cases", required=True,
                        help="JSON case file: a list or {cases: [...]}")
    verify.add_argument("--output-file", action="append", dest="output_file",
                        help="declared output file to compare (repeatable)")
    verify.add_argument("--timeout", type=float, default=10.0)
    verify.add_argument("--goal", default="")
    verify.add_argument("--report", help="write a signed .json or .html report")
    verify.add_argument("--json", action="store_true")
    verify.set_defaults(func=_cmd_verify)

    corpus = sub.add_parser("corpus", help="durable behavioral corpora")
    corpus_sub = corpus.add_subparsers(dest="corpus_cmd", required=True)
    corpus_cap = corpus_sub.add_parser("capture",
                                       help="record original behavior as regression cases")
    corpus_cap.add_argument("--target", required=True)
    corpus_cap.add_argument("--cases", help="JSON case file; generated when omitted")
    corpus_cap.add_argument("--output-file", action="append", dest="output_file")
    corpus_cap.add_argument("--timeout", type=float, default=10.0)
    corpus_cap.add_argument("--goal", default="")
    corpus_cap.add_argument("--dir", help="corpus directory")
    corpus_cap.add_argument("--json", action="store_true")
    corpus_cap.set_defaults(func=_cmd_corpus)
    corpus_list = corpus_sub.add_parser("list", help="list stored corpora")
    corpus_list.add_argument("--dir")
    corpus_list.add_argument("--json", action="store_true")
    corpus_list.set_defaults(func=_cmd_corpus)
    corpus_show = corpus_sub.add_parser("show", help="show one corpus by target hash")
    corpus_show.add_argument("sha")
    corpus_show.add_argument("--dir")
    corpus_show.add_argument("--json", action="store_true")
    corpus_show.set_defaults(func=_cmd_corpus)

    report = sub.add_parser("report", help="verify or render a signed report")
    report_sub = report.add_subparsers(dest="report_cmd", required=True)
    report_verify = report_sub.add_parser("verify", help="check a report signature")
    report_verify.add_argument("path")
    report_verify.add_argument("--json", action="store_true")
    report_verify.set_defaults(func=_cmd_report)
    report_render = report_sub.add_parser("render", help="render a report")
    report_render.add_argument("path")
    report_render.add_argument("--html", action="store_true")
    report_render.set_defaults(func=_cmd_report)

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

    bench = sub.add_parser("bench", help="run the capability benchmark")
    bench.add_argument("--provider", default="deepseek")
    bench.add_argument("--only", action="append", help="run only these task ids")
    bench.add_argument("--max-steps", type=int, default=24, dest="max_steps")
    bench.add_argument("--json", action="store_true")
    bench.set_defaults(func=_cmd_bench)

    serve = sub.add_parser("serve", help="run the local control API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8077)
    serve.add_argument("--store", default="./jobs", help="job store directory")
    serve.set_defaults(func=_cmd_serve)

    agent = sub.add_parser("agent", help="autonomous investigation agent")
    agent_sub = agent.add_subparsers(dest="agent_cmd", required=True)
    agent_run = agent_sub.add_parser("run", help="run an investigation")
    agent_run.add_argument("--goal", required=True)
    agent_run.add_argument("--target", help="path to the target binary")
    agent_run.add_argument("--project-dir", dest="project_dir",
                           help="project directory for coding tasks")
    agent_run.add_argument("--provider", default="deepseek",
                           help="llm provider (deepseek|mock)")
    agent_run.add_argument("--template", default="general",
                           help="agent role (general|reverse|engineer|researcher|security|mobile|writer|data)")
    agent_run.add_argument("--permission", default="execute",
                           choices=["read", "execute", "write"])
    agent_run.add_argument("--mode", default="",
                           choices=["", "ask", "build", "modify", "optimize",
                                    "autonomous", "direct", "reconstruction",
                                    "modernisation"],
                           help="interaction mode; it changes the contract, not the safety rules")
    agent_run.add_argument("--max-steps", type=int, default=24, dest="max_steps")
    agent_run.add_argument("--save", metavar="DIR", help="save the job record JSON here")
    agent_run.set_defaults(func=_cmd_agent_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Load .env (from cwd) so the model key is picked up without exporting it.
    from .config import load_dotenv

    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    # strip a leading "--" from sandbox REMAINDER
    if getattr(args, "argv", None) and args.argv and args.argv[0] == "--":
        args.argv = args.argv[1:]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
