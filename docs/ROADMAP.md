# ReverseAI — Roadmap & Status

A living map of what exists and what comes next. Update it as milestones land.

## Done (v0.1.x)

- **Analysis core** — PE/ELF/Mach-O. PE imports+exports; ELF dynamic imports,
  DT_NEEDED, function recovery; Mach-O segments + LC_SYMTAB symbols/functions.
  Entropy, strings, packer heuristics, structural diff. Cross-platform:
  Windows / Linux / macOS-iOS.
- **Sandbox lab** — bubblewrap (hardened), subprocess, experimental qiling
  emulation; factory auto-selects; refuses uncontained untrusted execution.
- **Agent** — ReAct loop, permission-tiered mediator + audit, evidence tiers,
  durable Job + store, context compaction for long runs.
- **Tools** — analysis, execution, byte-patch + regression verify + diff,
  LIEF structural edits (optional), coding (file ops + sandboxed run_command).
- **Providers** — DeepSeek + generic OpenAI-compatible + Anthropic + mock.
- **Service** — stdlib HTTP control API, secret-redacting logging.
- **Benchmark** — task harness with ground-truth checkers.
- **~130 tests**, CI workflow (push with a workflow-scoped token).

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
