# ReverseAI

> Understand. Modify. Rebuild.

An autonomous reverse-engineering engineer: give it a compiled program and a
goal in plain language; it investigates how the program works, makes the change,
tests it in isolation, and returns a working artifact plus the evidence.

This file is the persistent spec. Keep it honest and current — it is the source
of truth for what is actually built versus planned.

## Core principles (do not violate)

1. **Evidence vs. inference.** The analysis layer reports only what was parsed
   out of the file. Hypotheses, guesses, and AI conclusions live in a separate
   layer and are always labeled as such. Never let inference masquerade as fact.
2. **A successful build is not a working modification.** "It compiled" / "it
   launched" is never proof the requested change works. Every capability needs a
   test that demonstrates real behavior. Reports distinguish *believed* vs.
   *observed* vs. *verified*.
3. **The agent decides; tools execute.** Reasoning (what to investigate, which
   strategy) is separated from execution (parsing, patching, running). The agent
   requests operations through a controlled interface — it never gets raw host
   access just because it needs to analyze a file.
4. **Untrusted input by default.** Any binary may be hostile. Analysis is pure
   (no execution). Execution, when added, happens only in an isolated sandbox
   with no host filesystem/network/credential access.
5. **Honest scope.** We support a growing set of targets and modification types.
   We never claim "modify any binary." We report limitations plainly.

## Architecture (target)

```
User goal ─▶ Agent (orchestrator) ─▶ Analysis engine ─▶ Modification engine ─▶ Sandbox/testing ─▶ Verification ─▶ Artifact + report
```

| Layer              | Status      | Notes                                                        |
|--------------------|-------------|--------------------------------------------------------------|
| Analysis engine    | **started** | `reverseai/core` — format/arch/sections/imports/strings      |
| Agent orchestrator | planned     | reasoning loop over analysis tools; Claude first, model later |
| Modification engine| planned     | resource edit → binary patch → component → reimplementation  |
| Sandbox/testing    | planned     | isolated VM/container execution, regression comparison       |
| Verification       | planned     | structured report: believed/observed/verified + limitations |
| API + UI           | planned     | FastAPI job model, then React frontend                       |

## Current capability (v0.0.1)

Pure static analysis, zero third-party dependencies (stdlib + binutils only):
- Format detection (PE / ELF / Mach-O) by magic.
- Hashes (md5/sha1/sha256), whole-file and per-section Shannon entropy.
- PE: machine/arch, bitness, entry point, subsystem, exe-vs-dll, sections,
  imported DLLs and symbols.
- ELF: class/endian, machine/arch, type, entry point, section table.
- String extraction (ASCII + UTF-16LE).
- CLI: `python -m reverseai analyze <file> [--json]`.

Optional future backends (`lief`, `capstone`, `pyelftools`, Ghidra) enhance this
but are never required to run the core.

## Stack

- Core engine: Python 3.14, stdlib-only where possible.
- Later: FastAPI (API), Redis/worker (jobs), PostgreSQL (job state), React/TS (UI).
- Dev/test: `unittest` (no deps). Keep the core runnable with zero installs.

## Running

```bash
python3 -m reverseai analyze /path/to/binary
python3 -m reverseai analyze /path/to/binary --json
python3 -m unittest discover -s tests -v
```

## Milestones

- **M1 — Investigation engine** *(in progress)*: ingest a binary, report the
  truth about it. ✅ format/arch/sections/imports/strings + tests.
  Next: dynamic disassembly of functions (capstone), import/export completeness,
  optional Ghidra backend, packer detection.
- **M2 — Modification + sandbox**: resource edits and byte-level patches applied
  in a controlled env; isolated execution; crash capture; revert.
- **M3 — End-to-end job**: upload → plan → analyze → modify → test → repair loop
  → artifact + verification report, measured against a benchmark of known tasks.

## Working agreements for Claude Code

- Build in small, testable stages. Every feature lands with a test.
- Never execute an untrusted/unknown binary on the host. Use the sandbox (once
  built); until then, analysis stays static.
- Prefer stdlib; add a dependency only when it clearly earns its place, and keep
  the core importable without it.
- Keep `models.py` serialization stable — it's the cross-layer contract.
