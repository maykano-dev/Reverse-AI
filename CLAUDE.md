# ReverseAI

> Understand. Modify. Rebuild.

An autonomous engineering agent built on one platform (model-driven agent +
policy-mediated tools + hardened sandbox). Three pillars:

1. **Reverse engineering (flagship):** give it a compiled program and a goal in
   plain language; it investigates how the program works, makes the change,
   tests it in isolation, and returns a working artifact plus the evidence.
2. **Software engineering:** read/write/edit code and run builds & tests in the
   sandbox — a general coding agent.
3. **Defensive security:** analysis, hardening, detection, and authorized
   testing — and the hardening that protects the platform itself.

The same agent loop, tool framework, and sandbox serve all three; capabilities
are added as tools, not forks.

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
| Analysis engine    | **working** | `reverseai/core` — format/arch/sections/imports/strings/disasm |
| Agent orchestrator | **working** | `reverseai/agent` — ReAct loop, tool registry, mediator, job |
| Provider layer     | **working** | `agent/providers` — DeepSeek (OpenAI-compatible) + mock      |
| Sandbox/testing    | **working** | `reverseai/sandbox` — hardened bubblewrap + subprocess lab   |
| Evidence/verify    | **started** | believed/observed/verified tiers + audit; regression TBD     |
| Modification engine| planned     | resource edit → binary patch → component → reimplementation  |
| API + UI           | planned     | FastAPI job model, then React frontend                       |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[docs/SECURITY.md](docs/SECURITY.md) for the full design and threat model.

## Current capability (v0.1.0)

Zero third-party dependencies required (stdlib + binutils; optional libs enhance):
- **Analysis:** PE/ELF/Mach-O detection, hashes, whole-file + per-section
  entropy, PE imports/exports, ELF dynamic imports + DT_NEEDED, function
  recovery from symbol tables, packer heuristics, string extraction, optional
  capstone disassembly, structural binary diff.
- **Sandbox lab:** secure-by-default isolated execution. Hardened bubblewrap
  backend (namespaces, no network, caps dropped, read-only system, tmpfs
  workdir) + resource-limited subprocess + experimental qiling emulation;
  auto-selects the strongest backend and refuses untrusted execution when none
  can contain it.
- **Agent:** autonomous ReAct loop with policy-mediated tools (permission tiers,
  audit log, exception containment), evidence tiers (believed/observed/verified),
  durable Job records + store, DeepSeek + mock providers.
- **Tools:** analysis (analyze/read_bytes/strings/disassemble/list_functions/
  assess_heuristics), execution (run_in_sandbox), modification (apply_byte_patch/
  verify_against_original/diff_modified; LIEF add_import/add_section when
  installed), coding (list_dir/read_file/write_file/edit_file/run_command).
- **Modify + verify:** byte-patch on a copy + behavioral regression in the
  sandbox; LIEF structural edits when installed.
- **Benchmark:** task harness with ground-truth checkers (capability tracking +
  training-trace collection).
- **Conversations:** multi-turn, stateful — follow-ups share target, evidence,
  and modified artifacts. The AI picks its own mode (read→execute→write), asks
  clarifying questions, verifies before finishing, and delivers the final file.
- **Hostile input:** bomb-safe archive extraction; malware-indicator detection
  (injection/anti-debug/C2/persistence/ransomware/keylogging APIs); every run is
  isolated and torn down, so a crash/bomb is contained.
- **Service + UI:** stdlib HTTP API with SSE streaming + a premium web UI (chat,
  live inline tool work, markdown, file upload + drag-drop, message queue,
  artifact delivery, custom controls, sidebar); the model is never exposed.
- **CLI:** `analyze`, `diff`, `caps`, `sandbox run`, `agent run`, `bench run`,
  `serve`.

Optional backends (`lief`, `capstone`, `qiling`, `angr`, Ghidra) enhance this
but are never required to run the core.

### Model / provider

Default model provider is **DeepSeek** (OpenAI-compatible). Set `DEEPSEEK_API_KEY`
(and optionally `DEEPSEEK_MODEL`, default `deepseek-chat`). The `LLMProvider`
seam means a future in-house model drops in without touching the agent. Train
the in-house model later on collected `Job` records; do not attempt before the
platform is producing verified traces.

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

- **M1 — Investigation engine** ✅ : ingest a binary, report the truth, and let
  the agent investigate it through tools. Done: analysis core, sandbox lab,
  agent loop, providers, evidence/audit, CLI, 51 tests.
  Next within M1: capstone/angr function recovery + CFG, Ghidra headless tool,
  packer detection heuristics, seccomp profile for the sandbox.
- **M2 — Modification + verification**: `modify/` package (LIEF-backed resource
  edits and byte patches on a *copy*), WRITE-tier tools, and a `verify/` module
  that diffs original vs modified behavior in the sandbox (regression).
- **M3 — End-to-end job at scale**: FastAPI + worker queue + Job store; upload →
  plan → analyze → modify → test → repair loop → artifact + verification report,
  measured against a benchmark of known tasks. Then the web UI.
- **M4 — In-house model**: collect verified `Job` traces → fine-tune an
  open-weight model → hybrid routing (own model + DeepSeek fallback).

## Working agreements for Claude Code

- Build in small, testable stages. Every feature lands with a test.
- Never execute an untrusted/unknown binary on the host. Use the sandbox (once
  built); until then, analysis stays static.
- Prefer stdlib; add a dependency only when it clearly earns its place, and keep
  the core importable without it.
- Keep `models.py` serialization stable — it's the cross-layer contract.
