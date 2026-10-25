<p align="center">
  <img src="docs/assets/welcome.png" alt="ReverseAI chat interface" width="880">
</p>

<h1 align="center">ReverseAI</h1>

<p align="center"><b>Understand. Modify. Rebuild.</b></p>

<p align="center">
  An autonomous engineering agent for compiled software and live websites.<br>
  Drop in a binary, an app, an archive, or a URL. Say what you want in plain language.<br>
  Watch it plan, reason, use real tools, test in a hardened sandbox, and hand back a verified result.
</p>

<p align="center">
  <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-blue"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="core zero dependencies" src="https://img.shields.io/badge/core-zero%20dependencies-success">
  <img alt="tests" src="https://img.shields.io/badge/tests-200%2B%20passing-brightgreen">
  <img alt="status" src="https://img.shields.io/badge/status-beta-orange">
  <a href="https://maykano-dev.github.io/Reverse-AI/"><img alt="landing page" src="https://img.shields.io/badge/landing-live-brightgreen"></a>
</p>

<p align="center">
  <a href="https://maykano-dev.github.io/Reverse-AI/">Live site</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#whats-new-in-02">What's new</a> ·
  <a href="docs/UNIFIED_AGENT.md">Feature map</a> ·
  <a href="#deploy-it">Deploy</a> ·
  <a href="docs/SECURITY.md">Security</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

---

## Why it is different

Most "AI + reverse engineering" demos stop at describing a binary. ReverseAI closes the loop: it reads the real bytes, reasons about them, **changes** them, and **proves the change works** in a sandbox before you ever see the result.

- **Evidence over inference.** The analysis layer reports only what it parsed. Guesses are a separate, labeled layer. Findings are tiered **believed → observed → verified**.
- **A visible, natural thought process.** A plan, a short reasoning timeline, tool cards with real output, sources, and evidence. No raw tool names, no "investigating" boilerplate.
- **Untrusted by default.** Analysis is pure. Execution happens only inside a hardened bubblewrap sandbox (no network, dropped capabilities, read-only system, tmpfs workdir) and is refused when nothing can contain it.
- **A real working memory.** Durable notes, web research with citations, scheduled routines, specialist agents, and conversations that survive a reload or a server restart.
- **Mobile first.** A PWA that works as a full chat app on a phone, with a drawer, safe areas, touch-sized controls, and an installable manifest.

## What's new in 0.2

| Area | What landed |
|---|---|
| **Thinking UI** | Plan + chain-of-thought timeline, collapsible steps, tool cards, findings, elapsed time, and a real stop button (`POST /jobs/:id/cancel`). |
| **Natural narration** | Tool calls become specific human sentences ("Looking at the bytes around 0x400", "Running it in the sandbox"), never internal names or "investigating". |
| **Memory** | Durable notes (`remember`, `recall`, `forget`) in a human-editable JSON store, plus a Memory panel. |
| **Research with sources** | `web_search` and `web_read`, SSRF-guarded, with Source cards and citations. Optional SearXNG endpoint. |
| **Routines** | Daily, weekday, weekly, every-N-minutes, or one-off scheduled tasks, managed from the UI or a tool. |
| **Specialists** | Eight agent templates (Everyday, Reverse engineer, Engineer, Researcher, Security, Mobile, Writer, Data) and a `delegate` tool for squads. |
| **Durable turns** | Every event is appended to a replayable log; conversations persist across restarts; reconnecting resumes from where you left off. |
| **Usage + feedback** | Token/cost estimates, monthly budget gate, and thumbs up/down stored for improvement. |
| **Mobile + PWA** | Rewritten mobile-first UI, installable app shell, notifications, and speech input. |
| **Better artifacts** | Descriptive, unique names like `app-patched-remove-license-check-8f3a1c.exe`, with size and SHA-256 in the delivery card. |
| **Unlimited-OCR** | Optional adapter for Baidu's Unlimited-OCR behind vLLM/SGLang, with Tesseract as the zero-setup fallback. |
| **Security** | Optional bearer auth, path allowlists for public deployments, operator-controlled network egress, redirect-validated SSRF, and a browser-render gate. |
| **Packaging** | The UI, vendor scripts, and Ghidra script are included in the wheel. The CI/Pages workflows are staged in `docs/github-workflows/` until a token with the `workflow` scope can push them. |

<p align="center">
  <img src="docs/assets/thinking.png" alt="Natural reasoning timeline with tool cards and evidence" width="880">
</p>

---

## Quick start

### The app

```bash
git clone https://github.com/maykano-dev/Reverse-AI.git
cd Reverse-AI

export DEEPSEEK_API_KEY=sk-...     # the model is configured server-side only
python3 -m reverseai serve         # open http://127.0.0.1:8077
```

No third-party packages are needed for the core. Python 3.11+ and standard binutils are enough. Optional libraries make it stronger:

```bash
pip install -e ".[enhanced]"       # lief, capstone, pyelftools
pip install -e ".[ocr]"            # pytesseract, pillow, pymupdf
```

### CLI

```bash
# Static analysis of any PE / ELF / Mach-O binary
python3 -m reverseai analyze /usr/bin/objdump

# Structural diff between two binaries
python3 -m reverseai diff ./app ./app.patched

# What can this host do (sandbox backends, emulators, optional libs)?
python3 -m reverseai caps

# Run a command in the hardened sandbox
python3 -m reverseai sandbox run --untrusted -- /bin/echo "hello from the lab"

# Autonomous run
python3 -m reverseai agent run \
  --goal "Explain what this program does and verify it by running it." \
  --target ./sample --permission write --save ./jobs

# Capability benchmark
python3 -m reverseai bench run

# Tests (no network, no API key)
python3 -m unittest discover -s tests
```

### Docker

```bash
docker build -t reverseai .
docker run -p 8077:8077 \
  -e DEEPSEEK_API_KEY=sk-... \
  -e REVERSEAI_AUTH_TOKEN=choose-a-token \
  -v reverseai-data:/data \
  reverseai
```

The image runs as an unprivileged user and drops privileges via the entrypoint. `REVERSEAI_AUTH_TOKEN` is required before exposing it to the internet.

---

## Deploy it

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/maykano-dev/Reverse-AI)

The included [`render.yaml`](render.yaml) creates a web service, a 1 GB data disk, and a health check. Set `DEEPSEEK_API_KEY` and `REVERSEAI_AUTH_TOKEN` in the dashboard. The app asks for the token on first load and then keeps it in the browser.

**Sandbox note.** Untrusted-code *execution* needs unprivileged user namespaces, which many PaaS hosts disable. On Render, analysis, chat, research, memory, routines, decompilation, and static website cloning all work; sandboxed execution is refused honestly. For full execution, use a VM/VPS that allows user namespaces. See [`docs/SECURITY.md`](docs/SECURITY.md) and [`docs/DEPLOY.md`](docs/DEPLOY.md).

---

## What it can do today

- **Analyze** PE / ELF / Mach-O (including fat/universal iOS), Android APK, and archives: headers, sections, entropy, imports/exports, DT_NEEDED, symbols, functions, strings, optional capstone disassembly, packer and malware indicators, and structural diff.
- **Decompile** to readable C through Ghidra headless (optional), with a Java script for modern Ghidra releases.
- **Modify + verify** byte patches and LIEF structural edits on a copy, then behavioral regression in the sandbox.
- **Clone + rebuild websites** with a static fetch engine and an opt-in headless render engine, packaged as a working offline bundle with a clean-room guardrail.
- **Research** the web with sources, read primary pages, and keep citations attached to the answer.
- **Remember** stable preferences and decisions across chats.
- **Schedule** recurring work with routines that run while the server is up.
- **Delegate** to specialist agents (researcher, engineer, reverse engineer, reviewer, writer, data).
- **Read untrusted files safely** with bomb-safe extraction, malware indicators, and optional Unlimited-OCR or Tesseract.
- **Chat** in a stateful, multi-turn conversation. Follow-ups share the target, evidence, sources, and rebuilt artifacts.
- **Stay durable** when the tab closes: reopen and reattach to the live event stream.
- **Speak and listen** with browser speech input and optional spoken replies.
- **Install it** as a PWA on a phone or desktop.

<p align="center">
  <img src="docs/assets/artifact.png" alt="A delivered artifact with a descriptive name, size, and SHA-256" width="880">
</p>

---

## The interface

| Desktop | Mobile |
|---|---|
| <img src="docs/assets/welcome.png" alt="Desktop welcome with agent templates"> | <img src="docs/assets/mobile.png" alt="Mobile welcome" width="300"> |

The interface is deliberately opinionated:

- **Plan first**, then a compact reasoning timeline. Each step is collapsible and contains the tool output that justified it.
- **Evidence chips** separate `verified`, `observed`, and `believed`, and the full report is one click away.
- **Sources** are real cards with favicons, not a footer of naked URLs.
- **Artifacts** show the filename, size, and SHA-256. The original file is never changed.
- **No internal names leak** into the conversation. The agent speaks like a person.

<p align="center">
  <img src="docs/assets/memory.png" alt="Memory panel with a saved note" width="880">
</p>

---

## Supported targets

| Platform | Format | Analysis depth |
|---|---|---|
| Windows | PE (.exe/.dll) | header, sections, imports, exports, entropy, heuristics |
| Linux | ELF | header, sections, dynamic imports + DT_NEEDED, function recovery, native sandboxed execution |
| macOS / iOS | Mach-O (arm64/x86_64, fat) | header, segments/sections, symbols, functions |
| Android | APK | manifest hints, permissions, DEX, ABIs, native ELF libraries |
| Web | HTML/JS site | static fetch or optional headless render → offline bundle |

ELF runs natively in the sandbox. Foreign-platform binaries run through Qiling emulation when installed and configured, or a QEMU VM backend (designed, not wired).

---

## Architecture

```
User goal
  │
  ▼
Agent (agent/)  ── orchestrator · conversation · tool registry · mediator · evidence · job
  │
  ├── Providers (DeepSeek · OpenAI-compatible · Anthropic · Ollama · mock)
  ├── Memory · Skills · Templates · Routines · Research
  ├── Tools (analysis, execution, modification, coding, memory, research, delegate)
  │
  ├── Analysis core (core/)  PE · ELF · Mach-O · strings · disasm · heuristics · diff
  ├── Modification (modify/) byte patches · LIEF structural edits
  ├── Verification (verify/) behavioral regression in the sandbox
  ├── Sandbox (sandbox/) bubblewrap · subprocess · qiling
  │
  └── Service (server/) HTTP + SSE · durable event log · auth · PWA UI
```

The full design is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The feature-by-feature map of what was unified from the agent products is in [`docs/UNIFIED_AGENT.md`](docs/UNIFIED_AGENT.md).

### How a turn works

1. **Intake.** The target is validated (size caps, symlink refusal). A conversation gets a persistent workspace.
2. **Plan.** The agent picks a template and publishes a short plan.
3. **Reason.** The model sees the system prompt, memory, skills, conversation, and tool specs.
4. **Act.** Each tool call goes through the mediator (permission tier, audit, exception containment). The UI receives a natural `reason` event before the result.
5. **Observe.** Tools append evidence at the right tier. Research appends sources. Every event is written to a durable log.
6. **Conclude.** The final answer, evidence summary, sources, usage, and artifact meta are streamed and saved.

---

## Optional power-ups

| Feature | Enable with | Notes |
|---|---|---|
| Decompilation | Ghidra + a compatible JDK | `REVERSEAI_GHIDRA`, `REVERSEAI_JDK` |
| Long-document OCR | `REVERSEAI_OCR_URL` | Baidu Unlimited-OCR behind vLLM/SGLang |
| Local OCR | `pip install -e ".[ocr]"` | Tesseract system package required |
| Emulation | `pip install qiling` + `REVERSEAI_QILING_ROOTFS` | For foreign-platform binaries |
| Richer search | `REVERSEAI_SEARCH_URL` | SearXNG-compatible JSON |
| Headless clone | `REVERSEAI_ALLOW_BROWSER_RENDER=1` | Off by default on shared hosts |
| Coding network | `REVERSEAI_ALLOW_CODING_NETWORK=1` | Off by default; operator decision |

---

## Configuration

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`, `DEEPSEEK_BASE_URL` | Default model provider |
| `REVERSEAI_PROVIDER` | `deepseek`, `openai`, `anthropic`, `ollama`, or `mock` |
| `REVERSEAI_AUTH_TOKEN` | Require a bearer token on every API call |
| `REVERSEAI_ALLOWED_ROOTS` | Colon-separated roots for file paths when auth is on (the store is always allowed) |
| `REVERSEAI_MONTHLY_BUDGET` | Pause paid models after this many USD |
| `REVERSEAI_STORE` | Job/event/conversation/artifact storage |
| `REVERSEAI_SEARCH_URL` | SearXNG-compatible research endpoint |
| `REVERSEAI_OCR_URL`, `REVERSEAI_OCR_MODEL` | Unlimited-OCR endpoint |
| `REVERSEAI_SKILLS` | Directory of markdown playbooks |
| `REVERSEAI_GHIDRA`, `REVERSEAI_JDK` | Decompiler locations |
| `REVERSEAI_QILING_ROOTFS` | Emulation rootfs |
| `REVERSEAI_ALLOW_BROWSER_RENDER` | Opt in to headless Chromium cloning |
| `REVERSEAI_ALLOW_CODING_NETWORK` | Opt in to network for `run_command` |

Copy [`.env.example`](.env.example) to `.env` for a local setup. Never commit it.

---

## Security and responsible use

- Analysis is pure and runs in-process with bounded parsers.
- Untrusted execution is refused unless bubblewrap (or another isolating backend) is available.
- The API optionally requires a bearer token; file paths are allowlisted when auth is on.
- Tool output, web pages, and memory are treated as **data, not instructions**.
- Previewed and cloned sites run in an opaque-origin iframe with no access to the app.
- Secrets are redacted from logs; the model key never reaches the browser.

Known gaps are listed honestly in [`docs/SECURITY.md`](docs/SECURITY.md): no seccomp filter, shared-kernel namespace sandbox, Ghidra runs on the host, and no multi-tenant isolation yet.

Use ReverseAI for interoperability, security research, debugging, recovering your own work, and authorized testing. Analyze and modify only software and sites you own or are authorized to work on.

---

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The suite covers real PE/ELF/Mach-O parsing, bubblewrap isolation, archive bombs, the full agent loop with a mock provider, SSE replay, durable conversations, cancellation, memory, routines, research parsing, OCR (mocked HTTP), naming, auth, and path guards. No network or API key is required.

---

## Roadmap

See [`docs/ROADMAP.md`](docs/ROADMAP.md). The next meaningful steps are:

- seccomp/landlock and cgroup limits for the sandbox
- multi-tenant auth, quotas, and object storage for artifacts
- a Redis worker and Postgres job store for scale
- an optional Docker workstation with a live desktop (the Xiryn-style layer)
- MCP connectors, hooks, and shareable agent templates
- collecting verified traces and fine-tuning an in-house model

---

## Contributing

Contributions are welcome. Start with [`CONTRIBUTING.md`](CONTRIBUTING.md). Every capability ships with a test. Never run untrusted code outside the sandbox, and keep the evidence tiers honest.

If ReverseAI is useful to you, a star helps other people find it.

## License

Released under the [MIT License](LICENSE). Free to use, modify, and build on. Use it responsibly and only on software and sites you own or are authorized to work on.
