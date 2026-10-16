# ReverseAI

**Understand. Modify. Rebuild.**

An autonomous reverse-engineering engineer. Hand it a compiled program and a
goal in plain language; it investigates how the program works, makes the change,
tests it in isolation, and returns a working artifact with evidence.

It already has three working layers — a dependency-free **analysis engine**, a
hardened **sandbox lab** for running untrusted binaries, and an autonomous
**agent** that investigates a target through policy-mediated tools. The
modification engine and web UI are next. See [CLAUDE.md](CLAUDE.md),
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and
[docs/SECURITY.md](docs/SECURITY.md).

## The app

```bash
export DEEPSEEK_API_KEY=sk-...        # the model is configured server-side only
python3 -m reverseai serve           # then open http://127.0.0.1:8077
```

A premium chat UI: drop a binary (PE / ELF / Mach-O) or archive, say what you
want, and watch ReverseAI investigate live in an isolated sandbox — then it
hands back the finished, verified file. The model behind it is never exposed to
users; set `REVERSEAI_PROVIDER` (deepseek · openai · anthropic) to choose it.

## Quick start (CLI)

No dependencies required for the core — Python 3.11+ and standard binutils.

```bash
# Static analysis of any PE / ELF / Mach-O binary
python3 -m reverseai analyze /usr/bin/objdump

# Structural diff between two binaries
python3 -m reverseai diff ./app ./app.patched

# What can this host do (sandbox backends, emulators, optional libs)?
python3 -m reverseai caps

# Run a command in the hardened sandbox (no network, read-only system)
python3 -m reverseai sandbox run --untrusted -- /bin/echo "hello from the lab"

# Autonomous investigation (needs DEEPSEEK_API_KEY)
export DEEPSEEK_API_KEY=sk-...
python3 -m reverseai agent run \
  --goal "Explain what this program does and verify it by running it." \
  --target ./sample --save ./jobs

# Run the capability benchmark
python3 -m reverseai bench run

# Start the local control API (http://127.0.0.1:8077)
python3 -m reverseai serve

# Tests (no network / no API key needed — uses the mock provider)
python3 -m unittest discover -s tests -v
```

### Control API

`serve` exposes a localhost JSON API: `GET /health`, `GET /caps`,
`GET /jobs`, `GET /jobs/<id>`, `POST /analyze {path}`, `POST /diff {a,b}`,
`POST /jobs {goal,target,provider,permission}`. It is a single-user control
surface — keep it bound to localhost.

## Supported targets

Cross-platform by design — not Windows-only:

| Platform | Format | Analysis depth |
|---|---|---|
| Windows | PE (.exe/.dll) | header, sections, imports, **exports**, entropy, heuristics |
| Linux | ELF | header, sections, **dynamic imports + DT_NEEDED**, **function recovery**, native sandboxed execution |
| macOS / iOS | Mach-O (arm64/x86_64) | header, segments/sections, **imported/exported symbols**, functions |

ELF runs natively in the sandbox; PE and other foreign-platform binaries run via
the Qiling emulation backend (when installed) or a QEMU VM.

## Layers

- **Analysis** (`reverseai/core`) — format/arch/bits, hashes, per-section
  entropy, PE imports, ELF sections, strings, optional capstone disassembly.
- **Sandbox** (`reverseai/sandbox`) — secure-by-default isolated execution.
  Auto-selects the strongest backend (hardened **bubblewrap** namespaces, or a
  resource-limited subprocess), blocks network, drops capabilities, enforces
  timeouts, and *refuses* to run untrusted code when nothing can contain it.
- **Agent** (`reverseai/agent`) — a ReAct tool-calling loop with a permission
  mediator + audit log, evidence tiers (believed/observed/verified), durable
  Job records, and a pluggable provider layer (**DeepSeek** + offline mock).

## Model

Uses **DeepSeek** by default (OpenAI-compatible). Configure via env:

```bash
export DEEPSEEK_API_KEY=sk-...          # required for `agent run`
export DEEPSEEK_MODEL=deepseek-chat     # or deepseek-reasoner
```

The provider is one swappable seam — a future in-house model slots in without
changing the agent.

## Optional power-ups

```bash
pip install reverseai[enhanced]   # lief, capstone, pyelftools
```

`qiling` (emulation) and `angr` (symbolic execution) are detected automatically
when installed. None are required to run the core.

## Status

`v0.1.0` — working analysis engine, hardened sandbox, and autonomous agent, with
51 passing tests. Not yet: binary modification, regression verification, the
HTTP API, or the web UI. Those are the next milestones (see CLAUDE.md).
