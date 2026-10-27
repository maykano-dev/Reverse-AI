# Audit remediation plan

This is the working checklist for the full-repository audit. It follows the
audit's own order: establish the baseline, prove the central workflow, strengthen
verification, then improve learning and platform quality.

Status: **living**. Each item is checked only when the code and an offline test
exist; `~` is a foundation, not a complete product.

## Phase 1 — baseline and measurement

- [x] Run the full suite on the current tree and record the baseline.
- [x] Enumerate every registered tool and its permission tier.
- [x] Add a tool-contract test: every tool must return a `ToolResult`, never
      raise, and every spec must be JSON-serializable.
- [x] Add CLI parser contracts for every subcommand.
- [x] Add server auth/path/route contracts, including `/world` and `/discover`.
- [x] Add a machine-readable repository audit script.
- [x] Add a reproducible test/benchmark report to the docs.

## Phase 2 — prove autonomous engineering

- [x] Expand the benchmark beyond three happy-path tasks.
- [x] Add development and held-out task sets.
- [x] Track verified success, regression, repair, false verification, refusal,
      cost, and time.
- [x] Add mutation testing to measure whether a corpus can actually detect a
      broken candidate.
- [x] Add differential fuzzing over seeds (bounded, sandbox-only) and a report.
- [x] Add a benchmark quality test that proves each checker can fail.
- [x] Make the benchmark runnable without an API key for deterministic tools.

## Phase 3 — independent verification

- [x] Separate the modifier from the verifier.
- [x] Add acceptance criteria and prohibited-change checks.
- [x] Add test-strength reporting from mutation kills.
- [x] Add false-verification checks to the benchmark.
- [x] Add a signed proof package with the mutation score and untested scope.
- [ ] Add formal equivalence checking where a solver is available. Not bundled.

## Phase 4 — persistent engineering intelligence

- [x] Make the world model persistent and queryable.
- [x] Add provenance, invalidation, and unresolved questions.
- [x] Persist world-model summaries and discovery results on the `Job`.
- [x] Link requirements, experiments, modifications, tests, and decisions in the
      engineering graph.
- [x] Add verified-skill records with a holdout and staleness.
- [~] Add long-running mission recovery across process restarts: persisted
      state, checkpoints, and resume contract are built; a worker restart is not
      wired.

## Phase 5 — safety and sandbox

- [x] seccomp denylist on x86_64 with an honest report.
- [x] Network, filesystem, environment, process-group, and timeout boundary
      tests.
- [ ] Landlock filesystem enforcement (kernel/backend dependent). Detection is reported; enforcement is not applied.
- [ ] cgroup v2 enforcement (requires a delegated cgroup). Detection is reported; enforcement is not applied.
- [x] Never run a target on the host when the sandbox is unavailable.
- [x] Keep high-risk capabilities denied by default and approval-gated.
- [ ] QEMU/Qiling foreign-platform execution end to end. Requires a kernel/rootfs or emulator configuration.

## Phase 6 — analysis depth

- [x] PE/ELF/Mach-O/APK metadata, sections, imports, exports, strings, entropy.
- [x] Bounded CFG and call graph.
- [ ] PE resources, version info, TLS callbacks, rich header. Not yet implemented.
- [ ] Mach-O dyld export trie and full dylib dependency map. Not yet implemented.
- [x] Direct call/jump cross-reference recovery (`core/xrefs.py`).
- [ ] Data-structure recovery and indirect/data xrefs.
- [ ] Packed/obfuscated binary unpacking pipeline. Not yet implemented.

## Phase 7 — product surface

- [x] CLI, HTTP API, SSE, mobile-first UI.
- [x] Signed reports, replay recipes, world/discover endpoints.
- [ ] Multi-tenant accounts, quotas, object storage, worker queue. Not built.
- [ ] Hosted demo and active CI (blocked on credentials/token scope). Landing page is live; app is not hosted.

## Non-negotiables

- [x] No delivery without a passing behavioral test.
- [x] No causal or discovery claim without evidence labeling.
- [x] No invented confidence percentages.
- [x] No target execution outside `reverseai/sandbox`.
- [x] No irreversible action without capability + approval + audit.

## Current baseline

- Date: 2026-10-25
- Version: 0.9.0
- Tests: 558 passing, 4 environment-dependent skips
- Tools: 58 (every one covered by the contract suite)
- Known skips: no-sandbox refusal path (because a sandbox exists), LIEF absence
  (because LIEF is installed), missing-provider-key paths (because a key is
  present), and foreign-platform execution (no configured VM/rootfs).
- Benchmark: development + held-out tasks, including false-verification and
  refusal metrics.
- Mutation: strong-corpus and weak-corpus tests included.
- Repository audit: `python3 -m reverseai audit` passes.
- Sandbox boundaries: network, host files, environment, timeout, workspace, and
  symlink refusal are tested.
