# ReverseAI: Roadmap and Status

A living map of what exists and what comes next. Updated with v0.9.0.

## Done

### v0.9.0: interactive surfaces and workspace design

- **Interactive surface protocol**: question, form, table, chart, graph, diff,
  code, progress, approval, file drop, and sandboxed custom view blocks.
- **`create_surface`** agent tool and `Job.surfaces` persistence.
- **Surface endpoints**: list, record an event, and continue the conversation
  with a structured response.
- **UI redesign**: warm palette, serif welcome, context header, suggestion cards,
  calmer composer, surface cards, smooth transitions, mobile behavior.
- **Live site preview**: generated entry pages are served from the workspace,
  shown as a Preview card, and opened automatically when fresh.
- **Web media**: image search (web + Wikimedia Commons), attributed image
  installation, and validated stylesheet/font/SVG installation.
- **Dev-server preview**: gated bubblewrap-backed `npm run dev`/local server
  launcher with a multi-tab preview browser.
- **Tests**: 577; 60 tools contract-tested.

### v0.8.0: gated dangerous surfaces and open-item closure

- **Desktop**: local session broker + loopback listener, allowlisted actions,
  bearer token, approval gate, audit; no input-injection backend.
- **Telegram**: read-only Bot API channel, pairing, chat allowlist, rate limits.
- **Payments**: idempotent intent ledger, limits, approval gate, deterministic
  mock provider; no card data or live processor.
- **MCP**: JSON-RPC client, manifest validation, allowlist, capability gate;
  host transport explicitly dangerous.
- **Hooks**: signed manifests, sandboxed runner, events, timeout, audit.
- **Self-training**: verified-trace dataset, redaction, holdout, improvement
  pipeline; no auto-training.
- **Self-deployment**: plan, dry run, scoped approval, injected transport,
  rollback; no auto-deploy.
- **Open items**: differential fuzzing, PE/Mach-O depth, Landlock/cgroup/QEMU
  surfaces, mission persistence, per-token quota, readiness verdict.
- **Tests**: 519.

### v0.7.0: audit remediation and evidence hardening

- **Tool contracts**: every tool is tested for schema, permission, narration, UI
  label, and empty-argument behavior. Broken web-research imports and partial-call
  crashes were fixed.
- **CLI/server contracts**: all commands, corpus/report/approvals, mock agent,
  auth, path boundaries, and world/discover routes.
- **Sandbox boundaries**: network, host files, environment, timeout, workspace,
  and symlink refusal.
- **Mutation testing**: `assess_test_strength` reports killed/survived mutants and
  weak cases.
- **Benchmark v2**: development + held-out tasks; verified success, regression,
  repair, false verification, refusal, cost, and time metrics.
- **Analysis depth**: direct call/jump xrefs and a source-repository map.
- **Repository audit**: `reverseai audit` checks version, dependencies, assets,
  tool metadata, doc links, secret hygiene, and test presence.
- **Persistent evidence**: world model, opportunities, hypotheses, and mutation
  strength survive in the Job and signed report.
- **Tests**: 454.

### v0.6.0: engineering intelligence layer

- **World model and engineering graph**: components, dependencies, records,
  provenance, invalidation, queries, and memory classes.
- **Autonomous discovery**: hidden features, undocumented interfaces,
  architecture/dependency risks, missing tests, unlockable capabilities, and
  falsifiable hypotheses, each with evidence and a next step.
- **Science loop**: hypothesis → experiment → prediction → observation → update,
  with environment errors kept separate and competing explanations tested rather
  than voted on.
- **Causal reasoning**: explicit mechanisms, interventions, counterfactuals, and
  correlation labels.
- **Digital twin**: contract simulation, affected components, predicted failures,
  and a hybrid simulated/live/unknown plan.
- **Design search**: weighted objectives, constraints, Pareto front, measured
  algorithm comparison with equivalence checks, and a sandboxed tool forge.
- **Product and proof**: specification-to-product plans, behavior contracts,
  proof packages, independent verification, calibration, and regression
  promotion.
- **Orchestration**: model router, tool manifests, capability map, mission
  control, budgets, trust tiers, foundry, skill learning, analogy, and failure
  review.
- **Domain contracts**: hardware, robotics, CAD, network, security, and computer
  operation foundations, with explicit refusals for physical/live claims.
- **Tests**: 385, including world, discovery, science, causal, design, twin,
  forge, product, proof, adapters, router, protocol, capability, mission,
  learning, and tool wiring.

The full ledger is [`docs/INTELLIGENCE_ROADMAP.md`](INTELLIGENCE_ROADMAP.md).

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
- **Tests**: 293, including corpus replay, CLI verification, checkpoint attacks,
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
- [x] mutation/fuzz testing and a curated per-target corpus.
- [ ] structured failure diagnosis between repair attempts.
- [x] MCP client with mediator permissions.
- [x] pre/post tool hooks with an operator policy.
- [x] more PE/Mach-O structure (resources, TLS, dylib dependencies, exports).
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
