# Changelog

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
