# ReverseAI 0.8.0 — Release Integrity and Implementation Audit

This audit was performed directly in the repository, not from the public README
alone. Every test result below was executed on this host. The baseline commit
was `85122a9c18baade362a6d2da3dfad3fde3077917`; the remediation described here is
the audit-fix commit that contains this document.

## 1. Commit and environment

| Item | Value |
|---|---|
| Baseline commit | `85122a9c18baade362a6d2da3dfad3fde3077917` |
| Version under test | 0.8.0 |
| OS | Linux 7.0.0-38-generic, x86_64 |
| Python | 3.14.4 |
| Sandbox backend | bubblewrap 0.11.1 |
| Compiler | cc (Ubuntu 15.2.0) |
| LIEF | installed |
| DeepSeek key | present |
| Working tree at baseline | clean |

The external review’s claim that `pyproject.toml` declared 0.5.0 and the README
still featured 0.5 was **not true of this checkout**. At baseline, `pyproject.toml`,
`reverseai/__init__.py`, the changelog, and the README all declared 0.8.0. The
real inconsistencies were elsewhere, listed in section 6.

## 2. Reproducible commands

```bash
git rev-parse HEAD
python3 --version
uname -a
bwrap --version
python3 -m unittest discover -s tests
python3 -m reverseai audit
python3 -m reverseai release check
python3 -m reverseai surfaces --json
python3 -m unittest tests.test_fuzz tests.test_missions_quota \
  tests.test_pe_extra tests.test_macho_extra tests.test_mcp_hooks \
  tests.test_remote_channels tests.test_payments tests.test_self_improvement \
  tests.test_open_items tests.test_qemu_surface tests.test_release_integrity \
  tests.test_failure_paths -v
python3 -m unittest tests.test_packaging_install -v
```

## 3. Actual test results

| Command | Result |
|---|---|
| Full suite | **519 tests, 519 passed, 4 skipped**, exit 0 |
| Targeted failure-path/feature suite | **63 tests, 63 passed**, exit 0 |
| Clean wheel build + install | **1 test passed**, exit 0 |
| `reverseai audit` | **PASS** |
| `reverseai release check` | **PASS** (version 0.8.0, baseline 519, 56 tools) |
| `reverseai surfaces --json` | success |
| Wheel | `reverseai-0.8.0-py3-none-any.whl`, installed and entry point ran |

The four skips are environmental:

1. no-sandbox refusal path — an isolating sandbox exists on this host;
2. LIEF absence — LIEF is installed;
3. missing DeepSeek-key path — a key is present;
4. server missing-provider-key path — a key is present.

The no-sandbox refusal path is now also tested directly with a mocked empty
backend list in `tests/test_failure_paths.py`, so it is no longer only a skipped
environmental path.

## 4. Feature-by-feature implementation status

| Feature | Status | Source | Test evidence | Honest limit |
|---|---|---|---|---|
| Differential fuzzing | **Implemented and tested** | `reverseai/verify/fuzz.py`, `differential_fuzz` in `agent/verify_tools.py` | `tests/test_fuzz.py` (2), targeted suite pass | Bounded mutations, not coverage-guided; no automatic minimization |
| Mission persistence/resume | **Implemented but incompletely tested** | `reverseai/missions.py`, `MissionStore` | `tests/test_missions_quota.py` (6), including restart simulation | Store/resume contract works; no worker process supervisor or state-machine executor |
| PE resources/debug/TLS/rich header | **Implemented and tested** | `reverseai/core/pe_extra.py`, `core/analyze.py`, `core/models.py` | `tests/test_pe_extra.py` (6) | Synthetic PE fixtures; not a broad real-world PE corpus |
| Mach-O dependency parsing | **Implemented and tested** | `reverseai/core/macho.py`, `core/analyze.py` | `tests/test_macho_extra.py` (2) | Synthetic load-command fixture; no export-trie parser |
| MCP client | **Implemented but incompletely tested** | `reverseai/mcp/client.py` | `tests/test_mcp_hooks.py` (8) | Protocol tested with in-memory transport; host `StdioTransport` is untested and explicitly dangerous |
| Hook runner | **Implemented and tested** | `reverseai/hooks/runner.py` | `tests/test_mcp_hooks.py` (8), sandboxed hook pass | Long-running/recursive hooks are not supported |
| Desktop-session broker | **Implemented and tested** | `reverseai/remote/desktop.py` | `tests/test_remote_channels.py` (8) | No VNC, no keyboard/mouse backend; input actions refused |
| Telegram read-only channel | **Implemented but incompletely tested** | `reverseai/remote/telegram.py` | `tests/test_remote_channels.py` (8) | Tests use a fake transport; real Bot API not exercised |
| Payment intent ledger | **Implemented and tested** | `reverseai/payments/ledger.py` | `tests/test_payments.py` (7) | Mock provider and injected HTTP provider; no live processor or card data |
| Deployment controller | **Implemented but incompletely tested** | `reverseai/deploy/controller.py` | `tests/test_self_improvement.py` (10) | Dry-run/mock webhook tested; no live cloud/SSH transport |
| Per-token quotas | **Partial foundation only** | `reverseai/security/quota.py` | `tests/test_missions_quota.py` (6) | Tracker is tested; HTTP routes are not wired to consume it |
| Verified-trace dataset pipeline | **Implemented and tested** | `reverseai/training/dataset.py`, `training/pipeline.py` | `tests/test_self_improvement.py` (10) | No model training, no weight deployment, no demonstrated capability gain |
| Landlock surface | **Partial foundation only** | `reverseai/sandbox/landlock.py` | `tests/test_open_items.py` (3) | ABI/ruleset planning only; no enforcement |
| cgroup v2 surface | **Partial foundation only** | `reverseai/sandbox/cgroup.py` | `tests/test_open_items.py` (3) | Detection/optional scope; no default enforcement |
| QEMU surface | **Partial foundation only** | `reverseai/sandbox/backends/qemu_backend.py` | `tests/test_qemu_surface.py` (3) | Command builder/preflight only; guest runner not implemented; execution refused |
| Release consistency | **Implemented and tested** | `reverseai/release.py`, `audit.py`, CLI `release check` | `tests/test_release_integrity.py` (4) | Static checks; test count is a checked baseline, not dynamically run from the audit command |
| Clean install | **Implemented and tested** | `tests/test_packaging_install.py` | 1 build/install/entry-point test | Local wheel only; no PyPI publication |

## 5. Security gaps and status

| Control | Status | Evidence / caveat |
|---|---|---|
| bubblewrap namespaces | Implemented | `sandbox/backends/bubblewrap.py` |
| seccomp | Implemented as x86_64 denylist | `sandbox/seccomp.py`; not an allowlist; non-x86_64 reports false |
| Network isolation | Implemented/tested | `tests/test_sandbox_boundaries.py` |
| Host filesystem isolation | Implemented/tested | `tests/test_sandbox_boundaries.py`; no `/etc/passwd` visibility |
| Environment clearing | Implemented/tested | `tests/test_sandbox_boundaries.py` |
| Timeout/process-group kill | Implemented/tested | `tests/test_sandbox_boundaries.py` |
| Landlock enforcement | **Not implemented** | ABI/ruleset plan only |
| cgroup v2 enforcement | **Not implemented** | Detection/optional scope only |
| QEMU VM execution | **Not implemented** | Refuses until a guest runner exists |
| MCP host transport | **Disabled by default, dangerous when enabled** | Requires `REVERSEAI_ALLOW_MCP_HOST=1`, `allow_host=True`, `mcp` capability; runs on host |
| Hooks | **Gated; sandboxed** | Signed manifest, event allowlist, sandboxed subprocess |
| Desktop input | **Disabled by design** | No VNC/input backend; input action names refused |
| Live payment processor | **Disabled by design** | Mock provider and injected HTTP provider only; no card data |
| Live deployment | **Disabled by design** | Dry run + injected HTTPS/loopback webhook; no bundled cloud/SSH |
| Multi-tenant accounts | **Not implemented** | Single bearer token; quota tracker not server-wired |
| Adversarial malware isolation | **Not independently established** | Boundary tests use controlled fixtures, not a hostile sample corpus |
| Ghidra/Chromium | **Host-side** | Documented in `SECURITY.md` |

The external audit’s statement that the security document still said these
surfaces were not implemented was correct for the baseline. It has been corrected
to distinguish **gated surfaces** from **live authority** and to list what remains
unbundled.

## 6. Documentation inconsistencies found and fixed

| Finding | Severity | Before | After |
|---|---|---|---|
| Audit checklist version stale | **P0** | `docs/AUDIT_REMEDIATION.md` said 0.7.0 | 0.8.0 |
| Testing baseline version stale | **P1** | `docs/TESTING.md` said 0.6.0 | 0.8.0 |
| README test badge stale | **P1** | `505+` | `519+` |
| README headings patchless | **P2** | `What's new in 0.8` | `What's new in 0.8.0` |
| Security doc contradicted 0.8 surfaces | **P0** | Said desktop/MCP/hooks/payments “not implemented” | Gated-surface list + explicit unbundled list |
| Audit checklist still marked fuzzing missing | **P1** | `[ ]` | `[x]` with bounded-test note |
| No release consistency check | **P0** | none | `reverseai/release.py`, `release check`, audit check |
| No clean-install test | **P0** | none | `tests/test_packaging_install.py` |

The external review also claimed `pyproject.toml` was 0.5.0 and the README was
still 0.5. That was not true at this commit; both were 0.8.0. The audit report is
recording the actual state rather than repeating the stale claim.

## 7. Bugs found during the audit

1. **Release metadata drift (P0, fixed).** The audit and testing baselines,
   README badge, and README version headings had drifted from the package
   version. A release check now fails if they diverge.
2. **Security documentation drift (P0, fixed).** `SECURITY.md` described the
   0.8 surfaces as unimplemented, contradicting the code and changelog.
3. **Fuzzing completion drift (P1, fixed).** The audit checklist still said
   differential fuzzing was missing after `verify/fuzz.py` and its tests landed.
4. **Missing clean-install verification (P0, fixed).** There was no test that
   built the wheel, installed it into a clean target, and ran the entry point.
5. **Missing direct missing-sandbox test (P1, fixed).** The no-sandbox path was
   only skipped when a sandbox existed. A mocked empty-backend test now proves
   the fail-closed behavior.

No runtime regression was found in the exercised 0.8 paths. The remaining issues
are unexercised live integrations and incomplete enforcement, not hidden test
failures.

## 8. Severity and priority of remaining findings

| Finding | Severity | Priority | Why |
|---|---|---|---|
| Landlock/cgroup not enforced | High | P0 | Untrusted native code still relies on bubblewrap + denylist + RLIMITs |
| QEMU guest runner absent | High | P0 | Foreign-platform execution remains unverifiable |
| MCP host transport untested/unsandboxed | High | P0 | Third-party server code runs on the host when explicitly enabled |
| Server quota not wired | Medium | P1 | Quota module exists but does not protect HTTP routes |
| Worker-backed mission resume absent | Medium | P1 | Persistence contract exists; long-running process recovery is not operational |
| Real Telegram/payment/deployment integrations untested | Medium | P1 | Fake/injected transports prove the contract, not a live provider |
| Multi-tenant accounts absent | Medium | P2 | Single token; no per-user isolation |
| Data-structure/indirect-xref analysis absent | Medium | P2 | Core reverse-engineering depth gap |
| No adversarial malware corpus | Medium | P1 | Boundary tests are controlled, not hostile-sample validation |
| CI not active | Medium | P0 | Regressions rely on local runs |

## 9. Exact recommended fixes

1. **Make CI authoritative and fail the build on `release check` or `audit`.**
   Use the staged workflows in `docs/github-workflows/` once the token has
   `workflow` scope.
2. **Wire `QuotaTracker` into `/jobs`, `/jobs/start`, `/verify`, and `/discover`**
   with a `429` response and a test for the second over-quota request.
3. **Add a real worker/mission executor** with persisted state transitions and
   idempotency keys for side effects. The store/recovery contract already exists.
4. **Enforce Landlock and cgroup v2 where available, and refuse when requested
   but unavailable.** Keep bubblewrap as an additional layer.
5. **Complete the QEMU guest runner** (or an equivalent VM backend) and test
   stdout/exit propagation in a disposable guest.
6. **Add a live-integration staging suite** for Telegram, MCP host transport,
   payment HTTP adapter, and deployment webhook, each using an isolated fake
   server rather than real money or production infrastructure.
7. **Add a real-world corpus** for PE/Mach-O analysis and fuzzing; the current
   fixtures are synthetic and controlled.

## 10. Remaining unverified claims

- Real Telegram Bot API behavior.
- A live payment processor and its reconciliation/failure handling.
- A live deployment endpoint and real rollback.
- A real MCP server over host stdio.
- A desktop input backend (intentionally absent).
- QEMU execution end to end.
- Landlock and cgroup enforcement.
- Worker restart/resume under a real crash.
- Per-token quotas enforced by the HTTP server.
- Multi-tenant isolation.
- Real-world benchmark performance with a configured model.
- PE/Mach-O behavior across a broad real-world corpus.
- Self-training producing a measurable capability improvement.
- Public app deployment and active CI.

## 11. Next three highest-priority engineering tasks

1. **Activate CI with the release/audit gate** so this consistency cannot drift again.
2. **Finish the isolation boundary**: Landlock/cgroup enforcement and a real VM
   guest runner, with fail-closed tests.
3. **Make long-running work operational**: worker-backed mission transitions,
   idempotent side effects, and server quota enforcement.
