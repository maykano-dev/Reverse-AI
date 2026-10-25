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
from .templates import all_templates, get_template
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
        limit = max(1, min(int(args.get("limit", 100)), 2000))
        min_len = max(2, min(int(args.get("min_length", 5)), 64))
        found = extract_strings(data, min_len=min_len)
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


class ControlFlowTool(Tool):
    name = "build_control_flow_graph"
    description = (
        "Build a bounded basic-block and call graph for up to 32 functions. "
        "Shows block leaders, branch successors, call targets, and a rough "
        "cyclomatic complexity. Static only; a linear sweep can mix code and "
        "data, so treat it as an observed map, not proof of reachability."
    )
    parameters = {
        "type": "object",
        "properties": {
            "functions": {"type": "integer", "minimum": 1, "maximum": 32,
                          "default": 12},
        },
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from ..core.cfg import analyze_control_flow

        target = _require_target(ctx)
        try:
            flow = analyze_control_flow(
                target, analyze_file(target),
                max_functions=min(int(args.get("functions", 12)), 32))
        except Exception as exc:
            return ToolResult.failure(f"control-flow analysis failed: {exc}")
        lines = [
            f"functions: {len(flow.functions)}  blocks: "
            f"{sum(len(f.blocks) for f in flow.functions)}  calls: "
            f"{sum(len(f.calls) for f in flow.functions)}"
        ]
        for f in flow.functions[:16]:
            lines.append(
                f"  {f.name} @ 0x{f.address:x}: {len(f.blocks)} blocks, "
                f"{f.edges} edges, complexity {f.cyclomatic_complexity}")
        if flow.warnings:
            lines.append("warnings: " + "; ".join(flow.warnings[:6]))
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"control-flow graph: {len(flow.functions)} functions, "
                f"{sum(len(f.blocks) for f in flow.functions)} blocks",
                source=self.name)
        return ToolResult.success("\n".join(lines), **flow.to_dict())


class XRefTool(Tool):
    name = "find_xrefs"
    description = (
        "Find bounded direct call/jump cross-references between recovered "
        "functions. Indirect calls and data references are not resolved; this "
        "is a lead map, not a complete call graph."
    )
    parameters = {"type": "object", "properties": {
        "function": {"type": "string",
                     "description": "optional function name to focus callers/callees"}}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from ..core.xrefs import find_xrefs

        target = _require_target(ctx)
        report = analyze_file(target)
        xrefs = find_xrefs(target, report)
        name = str(args.get("function") or "")
        lines = [f"{len(xrefs.refs)} reference(s) across {len(xrefs.functions)} functions"]
        if name:
            callers = xrefs.callers_of(name)
            callees = xrefs.callees_of(name)
            lines.append(f"callers of {name}: {len(callers)}")
            lines += [f"  0x{r['from_address']:x} ({r['kind']})" for r in callers[:12]]
            lines.append(f"callees of {name}: {len(callees)}")
            lines += [f"  0x{r['to_address']:x}" for r in callees[:12] if r['to_address']]
        if xrefs.warnings:
            lines.append("warnings: " + "; ".join(xrefs.warnings[:5]))
        return ToolResult.success("\n".join(lines), **xrefs.to_dict())


class AnalyzeRepositoryTool(Tool):
    name = "analyze_repository"
    description = (
        "Build a bounded structural map of a source repository: languages, "
        "build systems, imports, entry points, tests, and risk markers. It reads "
        "files only inside the job's project/workspace boundary."
    )
    parameters = {"type": "object", "properties": {
        "path": {"type": "string",
                 "description": "optional subdirectory inside the project"}}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from pathlib import Path

        from ..repo import build_repo_model

        root = Path(ctx.extra.get("project_dir") or ctx.workspace).resolve()
        candidate = Path(args.get("path") or root)
        if not candidate.is_absolute():
            candidate = root / candidate
        try:
            candidate = candidate.resolve()
        except OSError as exc:
            return ToolResult.failure(f"invalid path: {exc}")
        allowed = [root, Path(ctx.workspace).resolve()]
        if not any(candidate == p or candidate.is_relative_to(p) for p in allowed):
            return ToolResult.failure("repository path is outside the job workspace")
        try:
            model = build_repo_model(candidate)
        except (OSError, ValueError) as exc:
            return ToolResult.failure(f"repository scan failed: {exc}")
        if ctx.evidence is not None:
            s = model.summary()
            ctx.evidence.observed(
                f"repository: {s['files']} files, {len(s['languages'])} language(s), "
                f"{s['tests']} test file(s), {s['risk_markers']} risk marker(s)",
                source=self.name)
        lines = [f"repository: {model.root}",
                 f"files: {len(model.files)}  tests: {len(model.tests)}  "
                 f"entry points: {', '.join(model.entry_points) or 'none'}",
                 f"build: {', '.join(model.build_systems) or 'not detected'}"]
        for lang in model.languages[:8]:
            lines.append(f"  {lang['name']}: {lang['files']} file(s)")
        if model.risk_markers:
            lines.append("risk markers:")
            lines += [f"  {r['marker']} {r['path']}:{r['line']}"
                      for r in model.risk_markers[:10]]
        return ToolResult.success("\n".join(lines), repository=model.to_dict(),
                                  summary=model.summary())


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
        timeout = min(max(float(args.get("timeout_seconds", base.timeout_seconds)), 0.1), 120.0)
        policy = replace(
            base,
            allow_untrusted_execution=True,
            timeout_seconds=timeout,
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


class ReadTextFromImageTool(Tool):
    name = "read_text_from_image"
    description = (
        "Extract text from an image, screenshot, or PDF via OCR. Use for reading "
        "text in app screenshots, UI mockups, scanned docs, or images embedded in "
        "a file (helpful for mobile/app reverse engineering and design cloning). "
        "Defaults to the target; pass a path for another file."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "image/PDF path; defaults to target"},
        },
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from ..ocr import ocr_any_available, ocr_best

        if not ocr_any_available():
            return ToolResult.failure(
                "No OCR engine is configured. Install tesseract + pytesseract, or "
                "point REVERSEAI_OCR_URL at an Unlimited-OCR / vLLM / SGLang server.")
        path = args.get("path") or ctx.target_path
        if not path:
            return ToolResult.failure("no image path")
        res = ocr_best(path)
        if not res.ok:
            return ToolResult.failure(res.error or "OCR failed")
        if ctx.evidence is not None:
            ctx.evidence.observed(
                f"OCR extracted {len(res.text)} chars via {res.engine or 'ocr'}",
                source=self.name)
        return ToolResult.success(res.text[:12000] or "(no text found)",
                                  chars=len(res.text), pages=res.pages,
                                  engine=res.engine)


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
        max_fn = max(1, min(int(args.get("max_functions", 300)), 2000))
        res = decompile(target, max_functions=max_fn)
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
        limit = max(1, min(int(args.get("limit", 100)), 2000))
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
        claim = str(args.get("claim") or "").strip()
        confidence = str(args.get("confidence") or "").lower()
        if not claim:
            return ToolResult.failure("missing 'claim'")
        tier = {"believed": Confidence.BELIEVED,
                "observed": Confidence.OBSERVED,
                "verified": Confidence.VERIFIED}.get(confidence)
        if tier is None:
            return ToolResult.failure("confidence must be believed|observed|verified")
        ctx.evidence.add(claim, tier, source="agent",
                         detail=str(args.get("detail") or ""))
        return ToolResult.success(f"recorded [{tier.label}] {claim}")


class RememberTool(Tool):
    name = "remember"
    description = (
        "Save a durable note about the user or the work so later conversations "
        "start with context. Use for stable preferences, decisions, and facts "
        "worth keeping. Never store secrets, credentials, or raw private data."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["text"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        if ctx.memory is None:
            return ToolResult.failure("long-term memory is not enabled for this job")
        text = str(args.get("text") or "").strip()
        if not text:
            return ToolResult.failure("missing 'text'")
        try:
            note = ctx.memory.add(text, tags=args.get("tags"), source="agent")
        except ValueError as exc:
            return ToolResult.failure(str(exc))
        return ToolResult.success(f"remembered ({note['id']}): {note['text']}",
                                  note=note)


class RecallTool(Tool):
    name = "recall"
    description = (
        "Search long-term memory for notes that might be relevant. Call this when "
        "the user refers to something from an earlier conversation."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "default": 10},
        },
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        if ctx.memory is None:
            return ToolResult.failure("long-term memory is not enabled for this job")
        notes = ctx.memory.search(args.get("query", ""), limit=int(args.get("limit", 10)))
        if not notes:
            return ToolResult.success("(no matching notes)")
        body = "\n".join(f"- ({n['id']}) {n['text']}" for n in notes)
        return ToolResult.success(body, notes=notes)


class ForgetTool(Tool):
    name = "forget"
    description = "Delete a saved memory note by id."
    parameters = {
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        if ctx.memory is None:
            return ToolResult.failure("long-term memory is not enabled for this job")
        note_id = str(args.get("id") or "").strip()
        if not note_id:
            return ToolResult.failure("missing 'id'")
        ok = ctx.memory.delete(note_id)
        return (ToolResult.success(f"forgot {note_id}") if ok
                else ToolResult.failure(f"no note with id {note_id}"))


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Search the public web and return titles, URLs, and snippets. Use for "
        "current information, comparisons, and research. Follow up with web_read "
        "on the best results. Cite the URLs you actually use."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 10,
                            "default": 5},
        },
        "required": ["query"],
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from .research import ResearchError, search_web, source_card

        try:
            results = search_web(args["query"], int(args.get("max_results", 5)))
        except ResearchError as exc:
            return ToolResult.failure(f"search failed: {exc}")
        if not results:
            return ToolResult.success("(no results)")
        sources = [source_card(r.url, r.title, r.snippet) for r in results]
        body = "\n\n".join(
            f"{i + 1}. {r.title}\n   {r.url}\n   {r.snippet}" for i, r in enumerate(results))
        return ToolResult.success(body, results=[r.to_dict() for r in results],
                                  sources=sources)


class WebReadTool(Tool):
    name = "web_read"
    description = (
        "Fetch a public web page and return its readable text, title, and "
        "description. Use after web_search. Refuses private/internal hosts."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "max_chars": {"type": "integer", "minimum": 500, "maximum": 40000,
                          "default": 16000},
        },
        "required": ["url"],
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from .research import ResearchError, read_page, source_card

        try:
            page = read_page(args["url"], int(args.get("max_chars", 16000)))
        except ResearchError as exc:
            return ToolResult.failure(f"could not read page: {exc}")
        source = source_card(page.url, page.title, page.description)
        body = f"# {page.title}\n{page.url}\n\n{page.text}"
        return ToolResult.success(body[:20000], page=page.to_dict(), sources=[source])


class ListSkillsTool(Tool):
    name = "list_skills"
    description = "List reusable playbooks (skills) available on this host."
    parameters = {"type": "object", "properties": {}}
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        skills = ctx.extra.get("skills") or []
        if not skills:
            return ToolResult.success("(no skills installed)")
        body = "\n".join(f"- {s.name}: {s.description}" for s in skills)
        return ToolResult.success(body, skills=[s.to_dict() for s in skills])


class ReadSkillTool(Tool):
    name = "read_skill"
    description = "Load the full instructions of a named skill/playbook."
    parameters = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }
    permission = Permission.READ

    def run(self, args, ctx) -> ToolResult:
        from .skills import find_skill

        skills = ctx.extra.get("skills") or []
        name = str(args.get("name") or "").strip()
        if not name:
            return ToolResult.failure("missing 'name'")
        skill = find_skill(skills, name)
        if skill is None:
            return ToolResult.failure(f"no skill named {name!r}")
        return ToolResult.success(skill.body[:14000], skill=skill.to_dict())


class DelegateTool(Tool):
    name = "delegate"
    description = (
        "Hand a self-contained piece of work to a specialist agent (researcher, "
        "engineer, reverse engineer, reviewer, writer, data). Use for a focused "
        "sub-task that benefits from a separate perspective. Returns that agent's "
        "conclusion and evidence."
    )
    parameters = {
        "type": "object",
        "properties": {
            "specialist": {
                "type": "string",
                "enum": [t.id for t in all_templates()],
            },
            "task": {"type": "string"},
            "target": {"type": "string",
                       "description": "optional file path; defaults to this job's target"},
        },
        "required": ["specialist", "task"],
    }
    permission = Permission.EXECUTE

    def run(self, args, ctx) -> ToolResult:
        from .orchestrator import Agent

        provider = ctx.extra.get("provider")
        if provider is None:
            return ToolResult.failure("delegation needs a configured model provider")
        depth = int(ctx.extra.get("delegate_depth", 0) or 0)
        if depth >= 2:
            return ToolResult.failure("delegation depth limit reached")
        specialist = args.get("specialist", "researcher")
        tmpl = get_template(specialist)
        maxp = ctx.extra.get("max_permission") or Permission.WRITE
        agent = Agent(
            provider,
            max_permission=maxp,
            max_steps=8,
            template=tmpl.id,
            memory=ctx.memory,
            skills=ctx.extra.get("skills"),
            delegate_depth=depth + 1,
        )
        job = agent.run(args["task"], target_path=args.get("target") or ctx.target_path,
                        project_dir=ctx.extra.get("project_dir"))
        if ctx.evidence is not None:
            for f in job.evidence.all():
                ctx.evidence.add(f.claim, f.confidence,
                                 source=f"delegate:{specialist}", detail=f.detail)
        summary = (
            f"{tmpl.name} finished ({job.status}, {job.steps} steps).\n\n"
            f"{job.final_answer or '(no conclusion)'}"
        )
        return ToolResult(ok=job.status == "completed", content=summary,
                          data={"sources": job.sources, "status": job.status,
                                "steps": job.steps, "usage": job.usage},
                          error=None if job.status == "completed" else job.status)


class ScheduleRoutineTool(Tool):
    name = "schedule_routine"
    description = (
        "Schedule a recurring task for the user (daily, weekdays, weekly, every N "
        "minutes, or once). Use when they say things like 'every morning at 8, "
        "brief me on ...'. Requires the routine scheduler to be enabled."
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "goal": {"type": "string"},
            "schedule": {
                "type": "object",
                "description": (
                    'e.g. {"kind":"daily","time":"08:00"} or '
                    '{"kind":"weekdays","time":"09:00"} or '
                    '{"kind":"weekly","weekday":0,"time":"09:00"} or '
                    '{"kind":"every","minutes":120} or '
                    '{"kind":"once","at":"2026-10-25T09:00"}'),
            },
            "template": {"type": "string"},
        },
        "required": ["goal", "schedule"],
    }
    permission = Permission.WRITE

    def run(self, args, ctx) -> ToolResult:
        store = ctx.extra.get("routine_store")
        if store is None:
            return ToolResult.failure("routines are not enabled in this session")
        permission = getattr(ctx.extra.get("max_permission"), "label", "write")
        try:
            routine = store.add(
                args.get("name") or args["goal"], args["goal"], args["schedule"],
                template=args.get("template") or "general",
                target=ctx.target_path, permission=permission)
        except (ValueError, TypeError) as exc:
            return ToolResult.failure(f"could not schedule: {exc}")
        return ToolResult.success(
            f"scheduled {routine.name} (next run {routine.next_run})",
            routine=routine.to_dict())


def default_tools() -> list[Tool]:
    from .corpus_tools import CaptureBehaviorCorpusTool
    from .intelligence_tools import intelligence_tools
    from .modify_engine import ChooseModificationStrategyTool, PlanAndModifyTool
    from .verify_tools import (
        AssessTestStrengthTool, DifferentialFuzzTool, DifferentialTestTool,
        VerifyModificationTool,
    )
    from .workspace_tools import (
        CheckExecutionReadinessTool,
        CreateCheckpointTool,
        ListCheckpointsTool,
        RestoreCheckpointTool,
        ReviewWorkspaceChangesTool,
    )

    tools = [
        HostCapabilitiesTool(),
        AnalyzeBinaryTool(),
        ReadBytesTool(),
        ListStringsTool(),
        DisassembleTool(),
        ListFunctionsTool(),
        ControlFlowTool(),
        XRefTool(),
        AnalyzeRepositoryTool(),
        AnalyzeApkTool(),
        AssessHeuristicsTool(),
        RunInSandboxTool(),
        RecordFindingTool(),
        RememberTool(),
        RecallTool(),
        ForgetTool(),
        WebSearchTool(),
        WebReadTool(),
        ListSkillsTool(),
        ReadSkillTool(),
        DelegateTool(),
        ScheduleRoutineTool(),
        VerifyModificationTool(),
        DifferentialTestTool(),
        DifferentialFuzzTool(),
        AssessTestStrengthTool(),
        CaptureBehaviorCorpusTool(),
        ChooseModificationStrategyTool(),
        PlanAndModifyTool(),
        CheckExecutionReadinessTool(),
        CreateCheckpointTool(),
        ListCheckpointsTool(),
        ReviewWorkspaceChangesTool(),
        RestoreCheckpointTool(),
    ]
    tools.extend(intelligence_tools())
    # Real decompilation when Ghidra is installed — a big capability upgrade.
    try:
        from ..decompile import ghidra_available

        if ghidra_available():
            tools.insert(5, DecompileTool())
    except Exception:
        pass
    # OCR when either a local engine or an Unlimited-OCR endpoint is configured.
    try:
        from ..ocr import ocr_any_available

        if ocr_any_available():
            tools.append(ReadTextFromImageTool())
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
