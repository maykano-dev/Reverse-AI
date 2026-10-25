# ReverseAI

> Understand. Modify. Rebuild.

An autonomous engineering agent built on one platform (model-driven agent +
policy-mediated tools + hardened sandbox). Three pillars:

1. **Reverse engineering (flagship):** give it a compiled program and a goal in
   plain language; it investigates how the program works, makes the change,
   tests it in isolation, and returns a working artifact plus the evidence.
2. **Software engineering:** read/write/edit code and run builds and tests in
   the sandbox, a general coding agent.
3. **Defensive security:** analysis, hardening, detection, and authorized
   testing, plus the hardening that protects the platform itself.

The same agent loop, tool framework, and sandbox serve all three. Capabilities
are added as tools, not forks.

This file is the persistent spec. Keep it honest and current. It is the source
of truth for what is built versus planned.

## Core principles (do not violate)

1. **Evidence vs. inference.** The analysis layer reports only what was parsed
   out of the file. Hypotheses, guesses, and AI conclusions live in a separate
   layer and are always labeled. Never let inference masquerade as fact.
2. **A successful build is not a working modification.** "It compiled" or "it
   launched" is never proof the requested change works. Every capability needs
   a test that demonstrates real behavior. Reports distinguish *believed*,
   *observed*, and *verified*.
3. **The agent decides; tools execute.** Reasoning is separated from execution.
   The agent requests operations through a controlled interface, never raw host
   access.
4. **Untrusted input by default.** Any binary, page, archive, or memory note may
   be hostile. Analysis is pure. Execution happens only in an isolated sandbox.
   Tool output is data, never instructions.
5. **Honest scope.** We support a growing set of targets and modification types.
   We never claim "modify any binary." We report limitations plainly.

## Architecture (current)

```
User goal ─▶ Agent ─▶ Analysis ─▶ Modification ─▶ Sandbox/testing ─▶ Verification ─▶ Artifact + report
```

| Layer | Status | Notes |
|---|---|---|
| Analysis engine | **working** | `core/` PE/ELF/Mach-O/APK, strings, disasm, heuristics, diff |
| Agent orchestrator | **working** | `agent/` ReAct loop, conversation, mediator, evidence, job |
| Provider layer | **working** | DeepSeek, OpenAI-compatible, Anthropic, Ollama, mock |
| Sandbox/testing | **working** | bubblewrap, subprocess, experimental qiling, hard refusal |
| Evidence/verify | **working** | believed/observed/verified + audit + behavioral regression |
| Modification engine | **working** | byte patches, LIEF structural edits, on a copy |
| Decompile | **working** | Ghidra headless + Java script for modern releases |
| Clone | **working** | static fetch; opt-in headless render |
| Memory/research/routines | **working** | durable notes, web sources, schedules |
| Templates/delegation | **working** | eight specialists, one-shot delegation |
| API + UI | **working** | stdlib HTTP + SSE, mobile-first PWA |
| Multi-tenant product layer | **planned** | accounts, quotas, object storage, worker queue |

## Current capability (v0.2.0)

Zero third-party dependencies required (stdlib + binutils; optional libs enhance):

- **Analysis:** PE/ELF/Mach-O detection, hashes, whole-file + per-section
  entropy, PE imports/exports, ELF dynamic imports + DT_NEEDED, function
  recovery, packer heuristics, string extraction, optional capstone
  disassembly, structural binary diff, APK structure + native ELF analysis.
- **Sandbox lab:** hardened bubblewrap (namespaces, no network, caps dropped,
  read-only system, tmpfs workdir), resource-limited subprocess, experimental
  qiling; auto-selects the strongest backend and refuses untrusted execution
  when none can contain it. Optional rootfs for qiling.
- **Agent:** ReAct loop with policy-mediated tools (permission tiers, audit log,
  exception containment), evidence tiers, durable Job records + store, natural
  narration, plan/step events, cancellation, context compaction.
- **State:** persistent conversations, replayable JSONL event logs, artifacts,
  long-term memory, routines, feedback, usage estimates.
- **Templates:** Everyday, Reverse engineer, Engineer, Researcher, Security,
  Mobile, Writer, Data; `delegate` for one-shot specialist work.
- **Research:** SSRF-safe search and page reading with sources and citations.
- **Skills:** markdown playbooks under `REVERSEAI_SKILLS` / `<store>/skills`,
  loaded on demand with `read_skill`.
- **Tools:** analysis, execution, modification, coding, memory, research,
  delegate, routines, archive extraction, website cloning, OCR.
- **Modify + verify:** byte patch on a copy + behavioral regression in the
  sandbox; LIEF structural edits when installed.
- **Decompile:** Ghidra headless with a Java GhidraScript for modern Ghidra and
  JDK-range detection. Optional.
- **OCR:** Baidu Unlimited-OCR via an OpenAI-compatible vLLM/SGLang endpoint,
  with Tesseract as a local fallback. Optional.
- **Clone:** static fetch + asset localisation; optional headless render is
  operator-gated because it runs a browser over untrusted pages.
- **Hostile input:** bomb-safe archive extraction; malware-indicator detection;
  every run is isolated and torn down.
- **Service + UI:** stdlib HTTP API with SSE, optional bearer auth, path
  allowlists, mobile-first PWA with a thinking timeline, sources, artifacts,
  memory, routines, usage, feedback, notifications, and speech input.
- **CLI:** `analyze`, `diff`, `caps`, `sandbox run`, `agent run`, `bench run`,
  `serve`.

## Important modules

| Path | Responsibility |
|---|---|
| `reverseai/core/` | Parsers and analysis contracts (`models.py` is stable) |
| `reverseai/agent/conversation.py` | Turn loop, events, state serialization |
| `reverseai/agent/narrative.py` | Human plan/step narration |
| `reverseai/agent/templates.py` | Roles / specialists |
| `reverseai/agent/memory.py` | Durable notes |
| `reverseai/agent/research.py` | Search/page reading + sources |
| `reverseai/agent/skills.py` | Markdown playbooks |
| `reverseai/routines.py` | Schedule math + scheduler |
| `reverseai/naming.py` | Descriptive artifact names |
| `reverseai/server/runs.py` | Durable runs, reattach, restore |
| `reverseai/server/app.py` | HTTP API, auth, path guard, static assets |
| `reverseai/sandbox/` | Isolation backends + policy |
| `reverseai/security/` | Validation, limits, archives, SSRF-safe fetch |
| `reverseai/server/static/` | Mobile-first UI (no build step) |

## Stack

- Core engine: Python 3.11+ (developed on 3.14), stdlib-only where possible.
- UI: vanilla ES2020, local marked + DOMPurify, no build step.
- Storage: JSON/JSONL under `REVERSEAI_STORE`.
- Later: FastAPI or the stdlib server at scale, Redis/worker, PostgreSQL,
  object storage, a React/TS frontend if the product needs it.
- Dev/test: `unittest` (no deps). Keep the core runnable with zero installs.

## Running

```bash
python3 -m reverseai analyze /path/to/binary
python3 -m reverseai analyze /path/to/binary --json
python3 -m reverseai serve
python3 -m unittest discover -s tests -v
```

## Working agreements for coding agents

- Build in small, testable stages. Every feature lands with a test.
- Never execute an untrusted/unknown binary on the host. Use the sandbox.
- Prefer stdlib; add a dependency only when it clearly earns its place, and keep
  the core importable without it.
- Keep `models.py`, `Tool`, `LLMProvider`, and `Sandbox` stable. They are the
  cross-layer contracts.
- Keep the UI honest: no raw tool names, no "investigating" boilerplate, no
  claims that a build equals a verified change.
- Do not add a vault, payments, or remote control without a separate threat
  model. Those are deliberately deferred.
- Update `docs/UNIFIED_AGENT.md` when a capability moves from partial/deferred
  to implemented.
