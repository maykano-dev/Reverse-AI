# ReverseAI: Roadmap and Status

A living map of what exists and what comes next. Updated with v0.4.0.

## Done

### v0.4.0: autonomous modification engine

- **Strategy selector**: scores resource_edit, byte_patch, component_replace,
  rebuild, and reimplement from the real analysis and the goal, with rationale,
  confidence, alternatives, warnings, and clarification.
- **Three modes**: Direct, Reconstruction, Modernisation, with user override and
  the chosen mode recorded on the Job.
- **Planner**: ordered investigate -> locate -> impact -> implement -> verify
  steps, component identification, blast-radius estimate, and scoped requests.
- **`plan_and_modify`**: end-to-end implementation through existing executors,
  then the Batch 1 verify+repair loop and signed report. Ambiguous requests ask
  instead of guessing; scoped changes require regression cases.
- **Environment fingerprint** in reports: sandbox backend, isolation level,
  network/filesystem controls, capability dropping, resource limits, seccomp.
- **High-risk capability policy**: remote control, vault, payments, workstation,
  squads, MCP, and hooks denied by default behind a master + per-capability opt-in
  (and a vault key).
- **Tests**: 240+, including selector, planner, scoped regression, end-to-end
  verified/broken runs, environment fingerprints, and capability policy.

### v0.3.0: verified delivery

- **Verified delivery gate**: `verify_modification` is the only path that can
  mark a modification verified. The orchestrator runs it before final delivery
  of any binary modification and withholds unverified artifacts.
- **Bounded repair loop**: failures are fed back to the model for a new
  candidate; default 3 attempts, max 10.
- **Differential testing**: original vs modified across an auto-generated or
  targeted corpus; stdin, output files, and unexpected regressions.
- **Signed reports**: JSON and self-contained HTML at `/jobs/<id>/report(.html)`;
  HMAC-SHA256 when `REVERSEAI_REPORT_KEY` is set, SHA-256 otherwise.
- **Verification UI**: attempt cards, blocked-delivery state, report link.
- **Server delivery test**: blocked artifacts are not persisted or served.
- **Tests**: 230+, including real sandbox verification and report tamper tests.

### v0.2.0: the unified, visible agent

- **Natural reasoning UI**: plan, chain-of-thought timeline, tool cards, findings,
  elapsed time, collapsible steps, real cancel.
- **Memory**: durable notes, `remember` / `recall` / `forget`, Memory panel.
- **Research**: `web_search` / `web_read`, SSRF-safe redirect handling, Source
  cards and citations, optional SearXNG.
- **Routines**: daily, weekdays, weekly, every-N-minutes, once; scheduler;
  Routines panel.
- **Specialists**: eight templates and a `delegate` tool.
- **Durable turns**: replayable JSONL event log, conversation persistence,
  reattach after reload/restart.
- **Usage and budget**: token/cost estimates, `/usage`, monthly gate.
- **Feedback and notifications**: stored ratings, desktop notifications.
- **Mobile first + PWA**: rewritten UI, manifest, service worker, speech input.
- **Artifact naming**: descriptive, unique names with size and SHA-256.
- **Unlimited-OCR adapter**: OpenAI-compatible vLLM/SGLang endpoint, Tesseract
  fallback.
- **Security**: optional bearer auth, path allowlists, operator-controlled
  network, browser-render gate, preview origin isolation, `.dockerignore`.
- **Packaging**: static assets and the Ghidra script ship in the wheel; CI
  builds and verifies the package.
- **Tests**: 200+ tests, including the new features and HTTP surface.

### Earlier

- Analysis core for PE/ELF/Mach-O/APK, entropy, imports/exports, functions,
  strings, disassembly, heuristics, diff.
- Bubblewrap/subprocess/qiling sandbox with hard refusal.
- Agent ReAct loop, mediator, evidence tiers, jobs, providers.
- Byte patching, LIEF edits, behavioral regression.
- Ghidra decompilation (including a Java script for modern Ghidra).
- Static website cloning and an opt-in rendered clone.
- Bomb-safe archives.
- CLI, HTTP API, SSE, web UI, benchmark.

## Next (priority order)

### M2: depth and safety
- [ ] seccomp-bpf and landlock profile for the sandbox.
- [ ] cgroup v2 limits for bubblewrap and subprocess.
- [ ] mutation/fuzz testing and a curated per-target corpus.
- [ ] automatic test generation from observed behavior (record -> replay).
- [ ] structured failure diagnosis between repair attempts.
- [ ] MCP client with mediator permissions.
- [ ] pre/post tool hooks with an operator policy.
- [ ] checkpoints and undo for conversations.
- [ ] inline diff review and a patch approval surface.
- [ ] more PE/Mach-O structure (resources, TLS, dyld export trie).

### M3: product surface
- [ ] per-user accounts, quotas, and usage metering.
- [ ] upload-based multi-tenant API and object storage for artifacts.
- [ ] Redis/worker queue + Postgres job store; resume/cancel across workers.
- [ ] shareable conversations and artifact links.
- [ ] a public landing page (GitHub Pages) and a hosted demo.

### M4: the model
- [ ] harvest verified job traces into a dataset, respecting licensing.
- [ ] fine-tune an open-weight model on reverse-engineering tasks.
- [ ] evaluate against DeepSeek on the benchmark.
- [ ] hybrid routing (in-house model + external fallback).

### The personal-agent layer (deferred, deliberately)
- [ ] Docker workstation per agent with a live desktop and take-over.
- [ ] Telegram remote control and pairing.
- [ ] encrypted vault for credentials and payment approval.
- [ ] persistent multi-agent squads with shared artifacts.

These are real product surfaces, not one-line features. They need a separate
threat model and should not be rushed into an unaudited local app. A deny-by-
default capability policy (`security/capabilities.py`) now makes accidental
enablement impossible: a master switch, a per-capability switch, and an
encryption key are required before any future implementation can start.

## Known gaps and debts

- Ghidra and optional headless Chromium run on the host; see `SECURITY.md`.
- No multi-tenant isolation yet.
- A single access token, no per-user accounts.
- `read_target` refuses symlinked agent targets (conservative default).
- Workstation, Telegram, vault, MCP, and hooks are not implemented.
- The CI/Pages workflows are staged in `docs/github-workflows/` until a token
  with the `workflow` scope can push them.
- Cost estimates are approximate and must be overridden for exact pricing.
- A passing verification proves only the declared inputs. Corpora are not
  exhaustive, and a SHA-256 report is tamper-evident but not keyed unless
  `REVERSEAI_REPORT_KEY` is set.
- The strategy selector is heuristic, not omniscient. It asks for clarification
  when the evidence is thin, but a confident-sounding choice still needs a
  passing behavioral test before delivery.
- High-risk capabilities are denied by default and remain unimplemented.

## How to continue

1. Read `CLAUDE.md` and `docs/ARCHITECTURE.md`.
2. Add a capability as a **Tool**, a **Sandbox backend**, or a **Provider**.
3. Ship a test and an honest limitation note with it.
4. Keep the core importable with zero dependencies.
5. Run `python3 -m unittest discover -s tests` before every commit.
