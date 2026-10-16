# ReverseAI — Roadmap & Status

A living map of what exists and what comes next. Update it as milestones land.

## Done (v0.1.x)

- **Analysis core** — PE/ELF/Mach-O (incl. fat/universal iOS). PE imports+
  exports; ELF dynamic imports, DT_NEEDED, function recovery; Mach-O LC_SYMTAB
  symbols/functions. Entropy, strings, packer heuristics, malware-indicator
  (suspicious-API) detection, structural diff. Cross-platform.
- **Sandbox lab** — bubblewrap (hardened), subprocess, experimental qiling;
  factory auto-selects; refuses uncontained untrusted execution. Bomb-safe
  archive extraction; ephemeral per-run isolation contains crashes/bombs.
- **Agent** — ReAct loop, multi-turn stateful conversations (shared target/
  evidence/artifacts), permission-tiered mediator + audit, evidence tiers,
  context compaction, Job + store. AI decides its own mode, asks clarifying
  questions, verifies before finishing, delivers the final file.
- **Tools** — analysis, execution, byte-patch + regression verify + diff,
  archive extraction, LIEF structural edits (optional), coding (file ops +
  sandboxed run_command).
- **Providers** — DeepSeek + generic OpenAI-compatible + Anthropic + mock; the
  model is server-chosen and never exposed to users.
- **Service + UI** — stdlib HTTP API with SSE streaming; premium web UI (chat,
  live inline tool work, markdown, upload + drag-drop, message queue, artifact
  delivery, custom controls, sidebar with search/artifacts/host/recents).
- **Benchmark** — task harness with ground-truth checkers.
- **~150 tests**, CI workflow (push with a workflow-scoped token).

## Next (priority order)

### M1 finish — analysis depth
- [ ] capstone/angr function-level CFG + call-graph tool (optional backends).
- [ ] Ghidra-headless decompile tool (run inside the sandbox).
- [ ] PE: resources/version info, TLS callbacks, rich header.
- [ ] Mach-O: LC_DYLD_INFO exports trie, dylib dependencies, fat-binary slices.
- [ ] seccomp-bpf profile for the sandbox (defense-in-depth; see SECURITY.md gap).
- [ ] cgroup v2 limits for the subprocess/bubblewrap backends.

### M2 — modification breadth
- [ ] LIEF: add/replace functions, patch imports, resource edits (beyond bytes).
- [ ] Code-cave / trampoline patching helpers.
- [ ] Automatic test generation from observed behavior (record → replay).
- [ ] Repair loop hardening: structured failure diagnosis between attempts.

### M3 — product surface
- [ ] Upload-based multi-tenant API (replace path-based control API); per-job
      isolation; object storage for artifacts.
- [ ] Async job queue (Redis/worker) + Postgres job store; resume/cancel.
- [ ] Web UI (upload, chat, live investigation view, artifact + report download).
- [ ] AuthN/Z, quotas, usage metering.

### M4 — the model
- [ ] Harvest verified Job traces from the benchmark + real runs into a dataset
      (filter by verified-tier outcomes; respect licensing).
- [ ] Fine-tune an open-weight model on RE tasks; evaluate vs DeepSeek on the
      benchmark.
- [ ] Hybrid routing: in-house model for what it does well, external fallback
      for hard reasoning.

## How to continue (for any engineer or agent)

1. Read `CLAUDE.md` (principles + contracts) and `docs/ARCHITECTURE.md`.
2. Add a capability as a **Tool** (`reverseai/agent/`) or a **Sandbox backend**
   (`reverseai/sandbox/backends/`) — the agent and API pick it up automatically.
3. Every feature ships with a test. Keep the core importable with zero deps.
4. Run `python3 -m unittest discover -s tests` before every commit.
5. Never run untrusted code outside the sandbox; keep evidence tiers honest.

## Known gaps / debts

- No seccomp/landlock filter yet (namespaces + caps only).
- Qiling/QEMU execution of PE/iOS binaries is wired but needs a configured
  rootfs / VM image to actually run foreign-platform targets.
- Control API is single-user/localhost; not yet multi-tenant.
- `read_target` refuses symlinked targets (conservative default).
- CI workflow lives at `.github/workflows/ci.yml` but is gitignored because the
  stored token lacks the `workflow` scope — push it with a scoped token.
