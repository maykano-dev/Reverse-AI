# ReverseAI: Roadmap and Status

A living map of what exists and what comes next. Updated with v0.5.0.

## Done

### v0.5.0: durable proof, replay, and a harder sandbox

- **Behavioral corpora**: capture the original's behavior by target hash and
  replay it as regression controls. Missing corpora fail honestly.
- **Model-free verification**: `reverseai verify` and signed replay recipes.
- **Checkpoints and undo**: automatic snapshots, diff review, safe restore.
- **Execution readiness**: native vs emulated vs analysis-only before a change.
- **seccomp**: x86_64 denylist through bubblewrap, recorded in the report.
- **Control-flow graphs**: basic blocks, edges, call targets, complexity.
- **Approvals and action gate**: capability + live scoped approval + audit.
- **Optional encrypted vault**: PBKDF2 + Fernet, deny-by-default.
- **Tests**: 292, including corpus replay, CLI verification, checkpoint attacks,
  readiness, seccomp, CFG, approvals, gate, and vault.

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
- [x] seccomp-bpf denylist for the sandbox (x86_64 bubblewrap).
- [x] automatic test generation from observed behavior (record -> replay).
- [x] checkpoints and undo for the workspace.
- [x] inline diff review and a restore surface.
- [x] bounded control-flow and call graphs.
- [x] action approvals and an audit gate.
- [ ] landlock profile and cgroup v2 enforcement.
- [ ] mutation/fuzz testing and a curated per-target corpus.
- [ ] structured failure diagnosis between repair attempts.
- [ ] MCP client with mediator permissions.
- [ ] pre/post tool hooks with an operator policy.
- [ ] more PE/Mach-O structure (resources, TLS, dyld export trie).
- [ ] foreign-platform execution via Qiling rootfs or a QEMU VM, end to end.
- [ ] a GitHub Action that runs `reverseai verify` on a pull request.

### M3: product surface
- [ ] per-user accounts, quotas, and usage metering.
- [ ] upload-based multi-tenant API and object storage for artifacts.
- [ ] Redis/worker queue + Postgres job store; resume/cancel across workers.
- [x] shareable reports with a replay recipe and signature check.
- [ ] shareable conversations and artifact links.
- [x] a public landing page (GitHub Pages).
- [ ] a hosted demo of the Python app (Render blueprint is ready).

### M4: the model
- [ ] harvest verified job traces into a dataset, respecting licensing.
- [ ] fine-tune an open-weight model on reverse-engineering tasks.
- [ ] evaluate against DeepSeek on the benchmark.
- [ ] hybrid routing (in-house model + external fallback).

### The personal-agent layer (deferred, deliberately)
- [ ] Docker workstation per agent with a live desktop and take-over.
- [ ] Telegram remote control and pairing.
- [x] encrypted vault primitive for credentials (optional; no payment execution).
- [ ] payment execution with human approval and a real ledger.
- [ ] persistent multi-agent squads with shared artifacts.

These are real product surfaces, not one-line features. They need a separate
threat model and should not be rushed into an unaudited local app. A deny-by-
default capability policy (`security/capabilities.py`) now makes accidental
enablement impossible: a master switch, a per-capability switch, and an
encryption key are required before any future implementation can start. The
approval ledger (`security/approvals.py`) and action gate (`security/gate.py`)
provide the human-in-the-loop boundary those features must use. The listener,
pairing flow, desktop backend, and payment processor are still absent on purpose.

## Known gaps and debts

- Ghidra and optional headless Chromium run on the host; see `SECURITY.md`.
- No multi-tenant isolation yet.
- A single access token, no per-user accounts.
- `read_target` refuses symlinked agent targets (conservative default).
- Workstation, Telegram, payments, MCP, and hooks are not implemented. The vault
  and approval primitives exist; the dangerous surfaces do not.
- seccomp is a denylist on x86_64 only; landlock and cgroup enforcement are not
  applied yet.
- Foreign-platform execution needs a configured Qiling rootfs or a QEMU VM.
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
