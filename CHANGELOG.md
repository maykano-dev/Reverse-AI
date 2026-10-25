# Changelog

## 0.5.0: durable proof, replay, and hardened host

### Added

- Durable behavioral corpora (`verify/corpus.py`, `agent/corpus_tools.py`):
  capture original exit/stdout/stderr/output-file behavior by target SHA-256 and
  replay it as regression controls with `use_corpus`.
- Model-free verification (`verify/replay.py`): `reverseai verify` produces the
  same signed record and report without a model or API key.
- Replay recipes in every signed report: target and artifact hashes, case names,
  and a copy-paste verification command.
- `reverseai corpus capture|list|show` and `reverseai report verify|render`.
- Workspace checkpoints (`checkpoints.py`, `agent/workspace_tools.py`): automatic
  pre-modification snapshots, bounded diff review, and conservative restore that
  refuses symlinks, device nodes, absolute paths, and `..`.
- Execution readiness (`sandbox/readiness.py`): native, emulated, or
  analysis-only verdict before a change is promised; `reverseai readiness`.
- x86_64 seccomp denylist (`sandbox/seccomp.py`) applied through bubblewrap's
  `--seccomp FD`. Blocks ptrace, mount/namespace escape, module loading,
  keyring, bpf, perf, io_uring, and similar attack-surface syscalls. The report
  records whether it was actually applied.
- Bounded control-flow and call graphs (`core/cfg.py`): basic blocks, branch
  edges, call targets, cyclomatic complexity; `reverseai cfg` and
  `build_control_flow_graph`.
- Approval ledger (`security/approvals.py`) and action gate (`security/gate.py`):
  short-lived, scoped, single-use HMAC approvals plus an append-only audit row
  for any future irreversible action.
- Optional encrypted vault (`security/vault.py`): PBKDF2-HMAC-SHA256 + Fernet,
  mode 0600, deny-by-default capability, no plaintext fallback.
- 44 new tests; total 293.

### Changed

- `Job` reports and signed reports include replay data.
- Differential case results include the arguments used, for replay.
- `SandboxPolicy` gains `seccomp` (default on where supported).
- Host capability detection reports seccomp, Landlock ABI, and cgroup v2.
- Version bumped to 0.5.0.

## 0.4.0: autonomous modification engine

### Added

- Strategy selector (`modify/strategy.py`): scores resource_edit, byte_patch,
  component_replace, rebuild, and reimplement from the real AnalysisReport and
  the goal. Returns rationale, confidence, alternatives, warnings, and a
  clarifying question when the evidence is thin.
- Three modes: Direct, Reconstruction, Modernisation. The engine recommends a
  mode; the user may override it; the chosen mode is recorded on the Job.
- Modification planner (`modify/planner.py`): ordered investigate -> locate ->
  impact -> implement -> verify plan, component identification, blast-radius
  estimate, and scoped "preserve the rest" detection.
- `choose_modification_strategy` (READ) and `plan_and_modify` (WRITE) agent tools.
- `plan_and_modify` runs the selected strategy through the existing executors
  (byte patch, LIEF structural edit, rebuild artifact, reimplementation
  artifact), then the verified delivery gate and signed report. It asks for
  clarification instead of guessing.
- Scoped changes require regression cases; an unrelated behavior change blocks
  delivery. End-to-end tests cover a correct change and a broken regression.
- Sandbox environment fingerprint in signed reports: backend, isolation level,
  network/filesystem controls, capability dropping, resource limits, seccomp.
- Deny-by-default capability policy (`security/capabilities.py`) for remote
  control, vault, payments, live workstation, persistent squads, MCP, and hooks.
  Master opt-in plus per-capability opt-in plus a vault key are required.
- 14 new tests; total 240+.

### Changed

- Verification reports include mode, strategy, plan steps, blast radius, and
  sandbox environment.
- The generic Job record now carries `mode` and `modification_plan`.
- High-risk features remain deliberately unimplemented, but cannot be enabled
  accidentally.

## 0.3.0: verified delivery

### Added

- Bounded verify-and-repair loop (`REVERSEAI_MAX_REPAIR_ATTEMPTS`, default 3,
  max 10). Failures are fed back to the model, which proposes a new candidate.
- `verify_modification` (EXECUTE): declared behavioral tests in the sandbox,
  attempt history, and the only path that may mark a modification verified.
- Automatic delivery gate before final delivery of any binary modification.
  Unverified artifacts are withheld with a plain-language reason.
- `differential_test` (EXECUTE): auto-generated or targeted input corpus,
  sandbox stdin, exit/stdout/stderr/output-file comparison, and unexpected
  regression detection.
- Sandbox stdin support for native backends; qiling refuses stdin honestly.
- Signed verification reports: `GET /jobs/<id>/report` (JSON) and
  `/report.html` (self-contained HTML), with HMAC-SHA256 when
  `REVERSEAI_REPORT_KEY` is set, otherwise SHA-256.
- Verification UI: attempt cards, blocked-delivery state, and a report link on
  the artifact card.
- Server-level test that blocked artifacts are neither persisted nor served.
- New tests across differential testing, repair, the delivery gate, report
  signing, the report routes, and sandbox stdin; total 230+.

### Changed

- `verify_against_original` is now explicitly a comparison-only tool; it records
  an observation and never authorizes delivery.
- A follow-up turn no longer re-delivers a previous turn's artifact.
- Blocked turns replace the model's optimistic conclusion with the actual
  verification reason.
- Uploaded binaries keep an owner-execute bit so they can be verified inside the
  sandbox (never run on the host).
- Version bumped to 0.3.0.

## 0.2.0: the unified, visible agent

### Added

- Natural reasoning timeline: plan, chain-of-thought steps, tool cards, findings,
  elapsed time, collapse/expand, and a real cancel endpoint.
- Durable memory with `remember` / `recall` / `forget` and a Memory panel.
- Web research with `web_search` / `web_read`, SSRF-safe redirects, sources,
  citations, and an optional SearXNG endpoint.
- Routines with daily/weekday/weekly/every-N-minutes/once schedules and a
  background scheduler.
- Eight agent templates and a `delegate` tool for specialist work.
- Durable event logs and conversation persistence; reattach after reload or
  restart.
- Usage estimates, monthly budget gate, feedback storage, desktop notifications,
  speech input, and optional spoken replies.
- Mobile-first PWA: manifest, service worker, drawer, safe areas, touch targets.
- Descriptive, unique artifact names with size and SHA-256.
- Baidu Unlimited-OCR adapter (OpenAI-compatible vLLM/SGLang) with Tesseract
  fallback.
- Markdown skill playbooks under `REVERSEAI_SKILLS`.
- Optional bearer auth, path allowlists, operator-controlled coding network, and
  a browser-render gate.
- `.dockerignore`, unprivileged container runtime, and packaging checks. The CI
  and Pages workflows are staged in `docs/github-workflows/` because the push
  token lacks the GitHub `workflow` scope.
- 25+ new tests covering features, HTTP endpoints, auth, durability, and OCR.

### Changed

- The UI no longer exposes internal tool names or "investigating" phrasing.
- Artifacts are named from the target, operation, and goal instead of a generic
  suffix.
- Conversation workspaces are persistent on the server instead of orphaned
  temp directories.
- Clone rendering is opt-in on shared hosts.
- Version bumped to 0.2.0.

### Fixed

- SSRF via redirects in clone and proxy fetching.
- Same-origin preview iframe could reach the control API.
- Docker builds copied `.env` and ran as root.
- A cloned page could be served with the app's origin.
- `analyze_file` could bypass size caps through the API.
- Cancellation actually stops the agent loop now.

## 0.1.1

- Ghidra decompilation improvements: JDK-range detection from
  `application.properties`, JDK save-file handling, and a native Java
  GhidraScript for modern Ghidra releases.

## 0.1.0

- Initial analysis core, sandbox, agent loop, providers, CLI, HTTP API, UI,
  modification, verification, clone, APK, OCR, and benchmark.
