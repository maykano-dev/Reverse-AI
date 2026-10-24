# ReverseAI

### Understand. Modify. Rebuild.

**ReverseAI is an autonomous engineering agent that takes compiled software or a
live website, figures out how it works, makes the change you ask for in plain
language, tests it in an isolated sandbox, and hands back a finished, verified
file.**

Drop in a binary (PE / ELF / Mach-O), an archive, or a URL, say what you want in
your own words, and watch it investigate live — then collect the rebuilt
artifact plus the evidence that it actually works.

![status](https://img.shields.io/badge/status-active-brightgreen)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![deps](https://img.shields.io/badge/core-zero%20dependencies-success)
![tests](https://img.shields.io/badge/tests-passing-brightgreen)

---

## Why it's different

Most "AI + reverse engineering" demos stop at *describing* a binary. ReverseAI
closes the loop: it reads the real bytes, reasons about them, **changes** them,
and **proves the change works** in a hardened sandbox before you ever see the
result.

- **Evidence over inference.** The analysis layer reports only what was parsed
  out of the file. Guesses live in a separate layer, always labeled. Findings
  are tiered *believed → observed → verified* — a successful build is never
  mistaken for a working modification.
- **The agent decides; tools execute.** A ReAct loop plans the work and calls
  policy-mediated tools (READ / EXECUTE / WRITE / DANGEROUS) through a permission
  mediator with a full audit log. It never gets raw host access.
- **Untrusted by default.** Any input may be hostile. Analysis is pure — no
  execution. Execution happens only inside a hardened **bubblewrap** sandbox
  (no network, dropped capabilities, read-only system, tmpfs workdir), and is
  *refused* when nothing on the host can contain it. Zip-bomb-safe extraction and
  malware-indicator detection are built in.

## What it can do today

- **Analyze** PE / ELF / Mach-O — headers, sections, per-section entropy,
  imports/exports, DT_NEEDED, function recovery, packer heuristics, strings,
  optional capstone disassembly, and structural binary diff.
- **Decompile** to real C via Ghidra headless (optional) — decompilation-first,
  far more useful to the agent than raw disassembly.
- **Modify + verify** — byte patches and LIEF structural edits applied to a
  *copy*, then a behavioral regression run in the sandbox to prove the change.
- **Clone & rebuild websites** — static fetch plus a headless-browser render
  engine for JavaScript-heavy sites, packaged into a working offline bundle,
  with a clean-room / legal guardrail.
- **Read untrusted files safely** — bomb-safe archive extraction, malware
  indicators (injection / anti-debug / C2 / persistence / ransomware /
  keylogging), optional OCR for images and PDFs.
- **Chat** — multi-turn and stateful. Follow-ups share the target, evidence, and
  rebuilt artifacts. The agent picks its own mode, asks clarifying questions,
  verifies before finishing, and delivers only the final file.

## The app

```bash
export DEEPSEEK_API_KEY=sk-...        # the model is configured server-side only
python3 -m reverseai serve           # then open http://127.0.0.1:8077
```

A premium, mobile-first chat UI: drag in a file or paste a URL, say what you
want, and watch the work stream live — code blocks with copy buttons, a natural
thinking trace, inline previews, an in-app browser, artifact delivery, and chat
history you can reopen. **The model behind it is never exposed to users**; set
`REVERSEAI_PROVIDER` (`deepseek` · `openai` · `anthropic` · `ollama`) to choose
it.

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

# Start the web app + control API (http://127.0.0.1:8077)
python3 -m reverseai serve

# Tests (no network / no API key needed — uses the mock provider)
python3 -m unittest discover -s tests -v
```

## Deploy it live

A container image is included. Any host that runs Docker works:

```bash
docker build -t reverseai .
docker run -p 8077:8077 -e DEEPSEEK_API_KEY=sk-... reverseai
```

One-click deploy with [`render.yaml`](render.yaml): create a new Blueprint on
Render pointing at this repo and set `DEEPSEEK_API_KEY`. **Note on the sandbox:**
untrusted-code *execution* needs unprivileged user namespaces, which many PaaS
hosts disable — there, analysis, chat, decompilation, and cloning all still
work; full sandboxed execution needs a VM/VPS that allows user namespaces (see
[docs/SECURITY.md](docs/SECURITY.md)).

## Supported targets

Cross-platform by design — not Windows-only:

| Platform | Format | Analysis depth |
|---|---|---|
| Windows | PE (.exe/.dll) | header, sections, imports, **exports**, entropy, heuristics |
| Linux | ELF | header, sections, **dynamic imports + DT_NEEDED**, **function recovery**, native sandboxed execution |
| macOS / iOS | Mach-O (arm64/x86_64) | header, segments/sections, **imported/exported symbols**, functions |
| Web | HTML/JS site | static + headless render → offline bundle |

ELF runs natively in the sandbox; PE and other foreign-platform binaries run via
the Qiling emulation backend (when installed) or a QEMU VM.

## Architecture

```
User goal ─▶ Agent (orchestrator) ─▶ Analysis ─▶ Modification ─▶ Sandbox/testing ─▶ Verification ─▶ Artifact + report
```

- **Analysis** (`reverseai/core`) — format/arch/bits, hashes, per-section
  entropy, imports, sections, strings, optional capstone disassembly, diff.
- **Sandbox** (`reverseai/sandbox`) — secure-by-default isolated execution.
  Auto-selects the strongest backend (hardened **bubblewrap** namespaces, or a
  resource-limited subprocess), blocks network, drops capabilities, enforces
  timeouts, and *refuses* untrusted code when nothing can contain it.
- **Agent** (`reverseai/agent`) — a ReAct tool-calling loop with a permission
  mediator + audit log, evidence tiers, durable Job records, and a pluggable
  provider layer.
- **Service + UI** (`reverseai/server`) — stdlib HTTP API with SSE streaming and
  a premium web UI; the model is never exposed.

See [CLAUDE.md](CLAUDE.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), and
[docs/SECURITY.md](docs/SECURITY.md) for the full design and threat model.

## Model

Uses **DeepSeek** by default (OpenAI-compatible). Configure via env:

```bash
export DEEPSEEK_API_KEY=sk-...          # required for `agent run` / the app
export DEEPSEEK_MODEL=deepseek-chat     # or deepseek-reasoner
```

The provider is one swappable seam (`deepseek` · `openai` · `anthropic` ·
`ollama`) — a future in-house model slots in without changing the agent.

## Optional power-ups

```bash
pip install reverseai[enhanced]   # lief, capstone, pyelftools
```

`qiling` (emulation), `angr` (symbolic execution), **Ghidra** (decompilation),
and **tesseract** (OCR) are detected automatically when installed. None are
required to run the core.

## Legal & responsible use

ReverseAI is for interoperability, security research, debugging, recovering your
own work, and authorized testing. Cloning reproduces *function*, not protected
expression (no copying of branding, trademarked assets, or proprietary content),
and the agent applies a clean-room guardrail. Analyze and modify only software
and sites you own or are authorized to work on. You are responsible for your use.

## License

© maykano-dev. All rights reserved. Licensing terms are being finalized.
