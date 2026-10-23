"""Built-in tools the agent uses to investigate and operate on a target.

These wrap the analysis core and the sandbox lab behind the Tool interface.
Read-tier tools are pure/observational; execute-tier tools run the target (or
analysis utilities over untrusted input) inside the hardened sandbox.
"""

from __future__ import annotations

from typing import Any

from ..core import analyze_file
from ..core.disasm import capstone_available, disassemble_bytes
from ..security.validate import ValidationError, read_target
from .evidence import Confidence
from .tools import Permission, Tool, ToolContext, ToolResult

_HEX_WINDOW_MAX = 4096


def _require_target(ctx: ToolContext) -> str:
    if not ctx.target_path:
        raise ValidationError("no target set for this job")
    return ctx.target_path


class HostCapabilitiesTool(Tool):
    name = "host_capabilities"
    description = (
        "Report what analysis/sandbox capabilities this host has (isolation "
        "backends, emulators, optional libraries). Call this first to know what "
        "is possible before planning."
    )
    parameters = {"type": "object", "properties": {}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from ..sandbox import detect_capabilities

        caps = detect_capabilities()
        lines = [f"best isolation: {caps.best_isolation()}",
                 f"can run untrusted: {caps.can_run_untrusted()}"]
        for k, v in caps.to_dict().items():
            lines.append(f"  {k}: {v}")
        return ToolResult.success("\n".join(lines), capabilities=caps.to_dict())


class AnalyzeBinaryTool(Tool):
    name = "analyze_binary"
    description = (
        "Statically analyze the target binary: format, architecture, bitness, "
        "entry point, sections (with entropy), imports, and string stats. Pure "
        "static inspection — does not execute anything."
    )
    parameters = {"type": "object", "properties": {}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        target = _require_target(ctx)
        report = analyze_file(target)
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"format={report.fmt.value}, arch={report.arch.value}, "
                f"bits={report.bits}", source=self.name)
        top = ", ".join(report.strings_sample[:8])
        lines = [
            f"format: {report.fmt.value}",
            f"arch: {report.arch.value} ({report.bits}-bit, {report.endian})",
            f"type: {report.binary_type}  subsystem: {report.subsystem}",
            f"entry: {hex(report.entry_point) if report.entry_point is not None else 'n/a'}",
            f"entropy: {report.entropy} (>7.0 suggests packing)",
            f"sections: {len(report.sections)}  "
            f"imports: {sum(len(v) for v in report.imports.values())} symbols "
            f"across {len(report.imports)} libs",
            f"needed libraries: {', '.join(report.needed_libraries[:8]) or 'n/a'}",
            f"imported symbols: {len(report.dynamic_symbols)}  "
            f"exports: {len(report.exports)}",
            f"strings: {report.string_count} (sample: {top})",
        ]
        if report.warnings:
            lines.append("warnings: " + "; ".join(report.warnings))
        return ToolResult.success("\n".join(lines), report=report.to_dict())


class ReadBytesTool(Tool):
    name = "read_bytes"
    description = (
        "Read a window of raw bytes from the target at a file offset and return "
        "a hex+ASCII dump. Use to inspect headers, specific structures, or "
        "patch sites."
    )
    parameters = {
        "type": "object",
        "properties": {
            "offset": {"type": "integer", "description": "byte offset into the file", "minimum": 0},
            "length": {"type": "integer", "description": f"bytes to read (max {_HEX_WINDOW_MAX})",
                       "minimum": 1},
        },
        "required": ["offset", "length"],
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        target = _require_target(ctx)
        offset = int(args["offset"])
        length = min(int(args["length"]), _HEX_WINDOW_MAX)
        data = read_target(target)
        chunk = data[offset:offset + length]
        if not chunk:
            return ToolResult.failure(f"no bytes at offset {offset} (file size {len(data)})")
        return ToolResult.success(_hexdump(chunk, offset),
                                  offset=offset, length=len(chunk))


class ListStringsTool(Tool):
    name = "list_strings"
    description = "List printable strings in the target, optionally filtered by a substring."
    parameters = {
        "type": "object",
        "properties": {
            "contains": {"type": "string", "description": "only strings containing this text"},
            "min_length": {"type": "integer", "minimum": 2, "default": 5},
            "limit": {"type": "integer", "minimum": 1, "default": 100},
        },
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from ..core.strings import extract_strings

        target = _require_target(ctx)
        data = read_target(target)
        needle = args.get("contains")
        limit = int(args.get("limit", 100))
        found = extract_strings(data, min_len=int(args.get("min_length", 5)))
        if needle:
            found = [s for s in found if needle in s]
        shown = found[:limit]
        body = "\n".join(shown) if shown else "(no matching strings)"
        return ToolResult.success(body, total=len(found), shown=len(shown))


class DisassembleTool(Tool):
    name = "disassemble"
    description = (
        "Disassemble a run of bytes from the target at a file offset. Uses "
        "capstone when available; otherwise falls back to objdump run inside "
        "the sandbox."
    )
    parameters = {
        "type": "object",
        "properties": {
            "offset": {"type": "integer", "minimum": 0},
            "length": {"type": "integer", "minimum": 1, "default": 128},
            "count": {"type": "integer", "minimum": 1, "default": 40,
                      "description": "max instructions"},
        },
        "required": ["offset"],
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        target = _require_target(ctx)
        report = analyze_file(target)
        offset = int(args["offset"])
        length = min(int(args.get("length", 128)), _HEX_WINDOW_MAX)
        count = int(args.get("count", 40))

        if capstone_available():
            data = read_target(target)
            code = data[offset:offset + length]
            if not code:
                return ToolResult.failure(f"no bytes at offset {offset}")
            try:
                insns = disassemble_bytes(code, report.arch, base_address=offset, count=count)
            except RuntimeError as exc:
                return ToolResult.failure(str(exc))
            body = "\n".join(str(i) for i in insns) or "(no instructions decoded)"
            return ToolResult.success(body, engine="capstone", instructions=len(insns))

        # Fallback: objdump over untrusted input, contained in the sandbox.
        return self._objdump_in_sandbox(target, ctx, count)

    def _objdump_in_sandbox(self, target, ctx, count) -> ToolResult:
        from ..sandbox import SandboxPolicy, create_sandbox
        from dataclasses import replace

        policy = ctx.sandbox_policy or SandboxPolicy()
        policy = replace(policy, ro_binds=list(policy.ro_binds) + [target])
        sb = create_sandbox(policy)
        res = sb.run(["/usr/bin/objdump", "-d", target], policy)
        if res.error:
            return ToolResult.failure(f"objdump sandbox error: {res.error}")
        lines = res.stdout_text().splitlines()
        disasm_lines = [ln for ln in lines if ":\t" in ln][:count]
        body = "\n".join(disasm_lines) or "(objdump produced no disassembly)"
        return ToolResult.success(body, engine="objdump",
                                  isolation=res.isolation.to_dict() if res.isolation else None)


class RunInSandboxTool(Tool):
    name = "run_in_sandbox"
    description = (
        "Execute the target binary (or an analysis command over it) inside the "
        "hardened sandbox and capture exit code, stdout, stderr, and the "
        "isolation actually applied. This is the only way to observe runtime "
        "behavior. Network is disabled; the filesystem is namespaced."
    )
    parameters = {
        "type": "object",
        "properties": {
            "args": {"type": "array", "items": {"type": "string"},
                     "description": "arguments to pass to the target"},
            "timeout_seconds": {"type": "number", "minimum": 0.1, "default": 10},
        },
    }
    permission = Permission.EXECUTE

    def run(self, args, ctx) -> ToolResult:
        from dataclasses import replace

        from ..sandbox import SandboxPolicy, SandboxUnavailable, create_sandbox

        target = _require_target(ctx)
        base = ctx.sandbox_policy or SandboxPolicy()
        policy = replace(
            base,
            allow_untrusted_execution=True,
            timeout_seconds=float(args.get("timeout_seconds", base.timeout_seconds)),
            ro_binds=list(base.ro_binds) + [target],
        )
        try:
            sb = create_sandbox(policy)
        except SandboxUnavailable as exc:
            return ToolResult.failure(str(exc))

        argv = [target] + [str(a) for a in args.get("args", [])]
        res = sb.run(argv, policy)
        iso = res.isolation.to_dict() if res.isolation else {}
        summary = (
            f"backend: {iso.get('backend')} (isolation level {iso.get('level')})\n"
            f"exit_code: {res.exit_code}  signal: {res.term_signal}  "
            f"timed_out: {res.timed_out}\n"
            f"duration: {round(res.duration_s, 3)}s\n"
            f"--- stdout ---\n{res.stdout_text()[:4000]}\n"
            f"--- stderr ---\n{res.stderr_text()[:2000]}"
        )
        if ctx.evidence is not None and not res.error:
            ctx.evidence.verified(
                f"target executed in sandbox: exit={res.exit_code}, "
                f"timed_out={res.timed_out}", source=self.name)
        return ToolResult(ok=not res.error, content=summary, data=res.to_dict(),
                          error=res.error)


class AnalyzeApkTool(Tool):
    name = "analyze_apk"
    description = (
        "Analyze an Android APK (the target): package name, requested "
        "permissions, DEX bytecode files, supported ABIs, and bundled native "
        "libraries analyzed as ELF binaries (arch + import counts). Use for "
        "mobile-app investigations. Full decompile/modify/resign needs external "
        "tooling; this is the structure + native-code analysis."
    )
    parameters = {"type": "object", "properties": {}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from ..mobile import analyze_apk

        target = _require_target(ctx)
        rep = analyze_apk(target)
        if not rep.is_apk:
            return ToolResult.failure("target is not a recognizable APK")
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"APK package={rep.package}, abis={rep.abis}, "
                f"{len(rep.dex_files)} dex, {len(rep.native_libs)} native libs",
                source=self.name)
        lines = [
            f"package: {rep.package}",
            f"permissions ({len(rep.permissions)}): {', '.join(rep.permissions[:10])}",
            f"dex files: {len(rep.dex_files)}  abis: {', '.join(rep.abis) or 'none'}",
            f"assets: {rep.asset_count}  resources: {rep.resource_count}",
            f"native libs ({len(rep.native_libs)}):",
        ]
        for lib in rep.native_libs:
            lines.append(f"  {lib.name} — {lib.arch} {lib.bits}-bit, {lib.imports} imports")
        return ToolResult.success("\n".join(lines), report=rep.to_dict())


class DecompileTool(Tool):
    name = "decompile"
    description = (
        "Decompile the target to readable C using Ghidra. Far more useful than "
        "disassembly for understanding logic. Optionally focus on one function by "
        "name. Static analysis only (the target is never run). Available only when "
        "Ghidra is installed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "function": {"type": "string",
                         "description": "only return this function's decompiled code"},
            "max_functions": {"type": "integer", "minimum": 1, "default": 300},
        },
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from ..decompile import decompile, ghidra_available

        if not ghidra_available():
            return ToolResult.failure("Ghidra is not installed on this host")
        target = _require_target(ctx)
        res = decompile(target, max_functions=int(args.get("max_functions", 300)))
        if not res.ok:
            return ToolResult.failure(res.error or "decompilation failed")
        code = res.code
        fn = args.get("function")
        if fn:
            # extract just the requested function block
            marker = f"// --- {fn} "
            idx = code.find(marker)
            if idx != -1:
                nxt = code.find("// --- ", idx + 10)
                code = code[idx:nxt if nxt != -1 else len(code)]
            else:
                return ToolResult.failure(f"function {fn!r} not found in decompilation")
        if ctx.evidence is not None:
            ctx.evidence.observed(f"decompiled {res.functions} functions with Ghidra",
                                  source=self.name)
        return ToolResult.success(code[:12000], functions=res.functions,
                                  truncated=len(code) > 12000)


class ListFunctionsTool(Tool):
    name = "list_functions"
    description = (
        "List functions recovered from the target's symbol table (name, address, "
        "size), optionally filtered by a name substring. Stripped binaries may "
        "return none — that is reported honestly."
    )
    parameters = {
        "type": "object",
        "properties": {
            "contains": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "default": 100},
        },
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        target = _require_target(ctx)
        report = analyze_file(target)
        funcs = report.functions
        needle = args.get("contains")
        if needle:
            funcs = [f for f in funcs if needle in f["name"]]
        limit = int(args.get("limit", 100))
        shown = funcs[:limit]
        if not report.functions:
            return ToolResult.success(
                "no functions recovered (binary may be stripped)", total=0)
        body = "\n".join(f"0x{f['address']:x}  {f['size']:>6}  {f['name']}" for f in shown)
        return ToolResult.success(body, total=len(funcs), shown=len(shown))


class AssessHeuristicsTool(Tool):
    name = "assess_heuristics"
    description = (
        "Run heuristic + malware-indicator checks over the target: packing, "
        "self-modifying sections, high entropy, and suspicious imported APIs "
        "(process injection, anti-debug, C2/download, persistence, ransomware "
        "crypto, keylogging). Returns INFERENCES, not facts — treat as leads to "
        "investigate (and to decide whether running it is safe), not verdicts."
    )
    parameters = {"type": "object", "properties": {}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from ..core.heuristics import assess

        target = _require_target(ctx)
        report = analyze_file(target)
        a = assess(report)
        if ctx.evidence is not None:
            if a.signals:
                ctx.evidence.believed(f"packing likelihood {a.packing_likelihood}",
                                      source=self.name, detail="; ".join(a.signals))
            if a.indicators:
                ctx.evidence.believed(f"malware suspicion {a.suspicion}",
                                      source=self.name, detail="; ".join(a.indicators))
        lines = [f"packing likelihood: {a.packing_likelihood}",
                 f"malware suspicion: {a.suspicion}"]
        if a.signals:
            lines.append("structure signals:")
            lines += [f"  - {s}" for s in a.signals]
        if a.indicators:
            lines.append("suspicious capabilities:")
            lines += [f"  - {i}" for i in a.indicators]
        if not a.signals and not a.indicators:
            lines.append("no notable signals")
        return ToolResult.success("\n".join(lines), assessment=a.to_dict())


class RecordFindingTool(Tool):
    name = "record_finding"
    description = (
        "Record a finding with an explicit confidence tier. Use 'believed' for "
        "a hypothesis, 'observed' for something read directly from the binary, "
        "'verified' for something demonstrated by running it. Keeps the final "
        "report honest."
    )
    parameters = {
        "type": "object",
        "properties": {
            "claim": {"type": "string"},
            "confidence": {"type": "string", "enum": ["believed", "observed", "verified"]},
            "detail": {"type": "string"},
        },
        "required": ["claim", "confidence"],
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        if ctx.evidence is None:
            return ToolResult.failure("no evidence log for this job")
        tier = {"believed": Confidence.BELIEVED,
                "observed": Confidence.OBSERVED,
                "verified": Confidence.VERIFIED}.get(args["confidence"].lower())
        if tier is None:
            return ToolResult.failure("confidence must be believed|observed|verified")
        ctx.evidence.add(args["claim"], tier, source="agent", detail=args.get("detail", ""))
        return ToolResult.success(f"recorded [{tier.label}] {args['claim']}")


def default_tools() -> list[Tool]:
    tools = [
        HostCapabilitiesTool(),
        AnalyzeBinaryTool(),
        ReadBytesTool(),
        ListStringsTool(),
        DisassembleTool(),
        ListFunctionsTool(),
        AnalyzeApkTool(),
        AssessHeuristicsTool(),
        RunInSandboxTool(),
        RecordFindingTool(),
    ]
    # Real decompilation when Ghidra is installed — a big capability upgrade.
    try:
        from ..decompile import ghidra_available

        if ghidra_available():
            tools.insert(5, DecompileTool())
    except Exception:
        pass
    return tools


def _hexdump(data: bytes, base: int = 0, width: int = 16) -> str:
    out = []
    for i in range(0, len(data), width):
        row = data[i:i + width]
        hex_part = " ".join(f"{b:02x}" for b in row)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
        out.append(f"{base + i:08x}  {hex_part:<{width * 3}}  {ascii_part}")
    return "\n".join(out)
