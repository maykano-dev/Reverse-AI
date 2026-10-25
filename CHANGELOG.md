# Changelog

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
