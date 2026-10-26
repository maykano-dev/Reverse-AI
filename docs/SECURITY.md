# ReverseAI: Security Model

ReverseAI ingests and executes software it does not trust. Security is the
constraint the architecture is built around. This document states the threat
model, the trust boundaries, the guarantees we make, and the guarantees we do
**not** yet make.

## Assets we protect

1. **The host** running ReverseAI: filesystem, network, credentials, processes.
2. **Other jobs / tenants**: one analysis must not observe or affect another.
3. **The user's original artifact**: never mutated in place.
4. **Secrets**: provider keys and access tokens never reach logs, transcripts,
   or the browser.

## Adversaries

- **The target binary.** Assume it is actively hostile: sandbox escape,
  resource exhaustion, network callbacks, host filesystem access, anti-analysis.
- **Prompt injection via target contents.** Strings, filenames, metadata, web
  pages, search snippets, and memory notes may contain text crafted to
  manipulate the model. Tool output is **data, not instructions.** The system
  prompt says this explicitly.
- **A buggy or over-eager model.** The mediator, not the model, decides what is
  allowed.
- **A remote API caller.** On a public deployment, assume unauthenticated
  clients will probe every endpoint with hostile paths and URLs.

## Trust boundaries

```
user (chat/CLI) ── trusted instructions ──► Agent orchestrator
                                              │
                              requests tools  │ (model output is UNTRUSTED)
                                              ▼
                                      Tool Mediator
                                              │ permission tier + audit
                                              ▼
                         Tools ──► Sandbox (untrusted code runs ONLY here)
                                              │
                         strong isolation     ▼
                                        the target binary
```

Only instructions from the user are authoritative. Everything observed through
a tool is untrusted data. Memory and web content are also data.

## API and deployment

- **Local by default.** `serve` binds `127.0.0.1` and prints a warning if auth
  is off.
- **Bearer auth.** Set `REVERSEAI_AUTH_TOKEN` before exposing the server. Every
  API route except the public shell, `/health`, and `/config` requires it.
  EventSource and download links may carry `?token=`; the server also sets an
  HttpOnly `SameSite=Lax` cookie after a valid token so iframe assets load.
- **Path allowlist.** When auth is on, `target`, `project_dir`, `/analyze`,
  `/diff`, `/modify`, and `/verify` paths must resolve under the store
  directory or `REVERSEAI_ALLOWED_ROOTS`. Local mode (no token) also allows the
  current directory for convenience.
- **Uploads** are streamed to a per-upload directory with a size cap.
- **Headers.** JSON responses use `no-store`; HTML uses a restrictive CSP;
  `X-Content-Type-Options: nosniff` and a referrer policy are set.
- **Preview isolation.** Cloned/built sites and proxied pages run in an iframe
  with `allow-scripts allow-forms allow-popups` but **no** `allow-same-origin`.
  A cloned page cannot reach the app's origin or its API.
- **Browser render gate.** Headless Chromium is opt-in
  (`REVERSEAI_ALLOW_BROWSER_RENDER=1`). On a shared host, static cloning is the
  safer default.

## Isolation guarantees (current)

Untrusted execution goes through `run_in_sandbox`, which uses the strongest
backend the host offers. On a typical Linux host that is **bubblewrap**:

| Control | Mechanism | Status |
|---|---|---|
| No network / exfiltration | `--unshare-net` | enforced + tested |
| Process isolation | `--unshare-pid --unshare-ipc --unshare-uts` | enforced |
| Read-only system | system dirs bound `ro`; writes confined to tmpfs `/work` | tested |
| No host env / secrets | `--clearenv`, explicit minimal env | tested |
| Privilege reduction | `--unshare-user`, `--cap-drop ALL` | enforced |
| Input injection | `--new-session` (blocks TIOCSTI) | enforced |
| Dangerous syscalls | x86_64 cBPF denylist via `--seccomp FD` (ptrace, mount/namespace escape, modules, keyring, bpf, perf, io_uring, …) | enforced when supported + tested |
| Resource exhaustion | RLIMIT cpu/mem/fsize/nofile + wall-clock timeout + process-group kill | tested |
| Lifetime | `--die-with-parent`; ephemeral workdir removed | enforced |

**Hard refusal:** if a job requests untrusted execution and no isolating backend
is available, ReverseAI refuses rather than falling back to the host. See
`sandbox/factory.create_sandbox`. `ExecResult.isolation` reports what was
actually enforced.

## Network safety

- Research (`web_search`, `web_read`), clone, and the browsing proxy validate
  the scheme and host on **every redirect hop**, reject private/loopback/
  link-local/reserved addresses, and cap response size and time.
- `run_command` network is **operator-controlled**:
  `REVERSEAI_ALLOW_CODING_NETWORK=1`. The model cannot turn it on.
- `run_in_sandbox` never has network unless the operator explicitly builds a
  policy that allows it.

## Secrets

- Provider keys are read from the environment or `.env` and are never logged.
- The redacting logger scrubs key-shaped tokens, bearer tokens, long hex
  strings, and the live values of known secret variables.
- `.env` is gitignored and excluded from the Docker build context.
- The browser never receives a provider key. `/config` reports readiness, not
  the model or key.

## High-risk capabilities are denied by default

The 0.9 release adds **gated surfaces**, not enabled authorities:

- Desktop session broker and loopback listener (no VNC/input backend).
- Read-only Telegram channel (no shell/payment/deployment commands).
- Payment intent ledger and provider boundary (mock provider; operator-supplied
  HTTPS/loopback adapter; no card data, no bundled live processor).
- MCP JSON-RPC client (host transport is explicit and dangerous).
- Signed, sandboxed hooks.
- Verified-trace dataset and benchmark-gated improvement pipeline.
- Deployment plan/controller with dry run, approval, injected transport, and
  separately approved rollback.

Every one is denied by default. Enabling one requires both
`REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES=1` and its own
`REVERSEAI_ENABLE_*` variable. A vault/payment capability also requires
`REVERSEAI_VAULT_KEY`. Any future feature must call
`CapabilityPolicy.require()` before touching the host, the network, or stored
credentials. `/config` and `/surfaces` report which surfaces are enabled, never
their secrets.

**A second gate covers irreversibility.** `security/gate.py` requires a live,
scoped, single-use approval issued by `security/approvals.py` (HMAC-SHA256,
short TTL, action and scope bound) and writes an append-only audit row. A
capability switch alone is not permission to charge a card, take over a
desktop, deploy an artifact, or run a remote command.

**The vault is optional and refuses to weaken.** `security/vault.py` requires
the `cryptography` package, derives a key with PBKDF2-HMAC-SHA256, stores Fernet
ciphertext at mode 0600, and raises rather than falling back to a homemade cipher
or plaintext.

Still **not bundled**: a real VNC/input backend, a live payment processor, a
public Telegram bot token, automatic training/weight deployment, automatic
production deployment, Landlock/cgroup enforcement, a QEMU guest runner, and
multi-tenant accounts. Those need a specific backend, credential, and threat
model; the interfaces and gates are present so they can be added without
inventing a weaker boundary.

## Gated dangerous surfaces

The v0.9 surfaces are deliberately narrow:

- **Desktop**: loopback listener with a bearer token, allowlisted actions, and a
  scoped approval for `takeover`/`focus`/`refresh`. No VNC endpoint and no
  keyboard/mouse injection backend. `type`, `click`, `shell`, and `exec` are
  refused by name.
- **Telegram**: only `/status`, `/jobs`, `/readiness`, `/discover`, and `/pair`.
  There is no shell, payment, deployment, or arbitrary-file command. A chat must
  be paired; messages are rate-limited and audited.
- **Payments**: no card fields, no live provider, amount/currency limits,
  idempotency keys, and a scoped approval for every charge. The bundled provider
  is a mock that moves no money.
- **MCP**: the protocol client is transport-agnostic. `StdioTransport` launches a
  host process only when both `REVERSEAI_ALLOW_MCP_HOST=1` and
  `allow_host=True` are set *and* the MCP capability is enabled. Prefer a
  sandbox/VM transport for untrusted servers.
- **Hooks**: signed manifests only, event allowlist, sandboxed subprocess,
  timeout, no host environment inheritance, audit.
- **Self-training**: only verified, delivery-allowed jobs become traces. Secrets
  are redacted, duplicates removed, and a deterministic holdout is kept. No
  automatic training or weight deployment.
- **Self-deployment**: dry run first, capability + approval, injected transport,
  and a separately approved rollback. No cloud/SSH transport is bundled.
- **QEMU/Landlock/cgroup**: surfaces and preflight are present; enforcement is
  not claimed. The bubblewrap namespace remains the active boundary.

## Discovery, world models, and domain adapters

- `/world` and `/discover` are read-only analysis endpoints. They parse the
  target and return a model/proposals; they do not execute or modify it.
- Discovery output is a lead with evidence, not a finding of a vulnerability.
  The model separates `observed` from `hypothesis`.
- A causal prediction is only made through an explicitly supplied mechanism.
  Correlation remains a hypothesis until an intervention or controlled
  experiment distinguishes it.
- A digital twin is a model, not the production system. Its hybrid plan names
  what must be tested live and what remains unknown.
- Hardware, robotics, CAD, network, and computer-operator adapters are
  contracts. They do not flash hardware, move a robot, run a geometry kernel,
  change a live network, or inject desktop input.
- Forged tools run only in the sandbox and are promoted only after their tests
  pass. They are not trusted just because the agent wrote them.
- The intelligence layer does not retrain, self-modify, or self-deploy. The
  foundry compares candidates against a baseline and a holdout; a human approves
  a deployment.

## Verified delivery and reports

- A modified binary is delivered only when `verify_modification` records a
  passing behavioral expectation from a sandbox run. The delivery gate runs
  before the final event; a missing test is a refusal, not an assumption.
- A failed test can trigger a bounded repair loop. Candidates accumulate in the
  workspace but are not exposed as delivered artifacts until they pass. The
  default bound is 3 attempts (max 10), configurable with
  `REVERSEAI_MAX_REPAIR_ATTEMPTS`.
- `verify_against_original` is comparison-only. It records an observation and
  cannot authorize delivery.
- Reports are signed over a canonical JSON representation. Set
  `REVERSEAI_REPORT_KEY` to use HMAC-SHA256; otherwise a plain SHA-256 digest is
  used. A SHA-256 digest is tamper-evident but not keyed: anyone can recompute
  it. Use a key when the report leaves your machine.
- A signature proves the report was not altered after signing. It does not make
  a weak test strong; read the declared inputs and expectations.
- Reports record the sandbox environment fingerprint (backend, isolation level,
  network/filesystem controls, capability dropping, resource limits, seccomp)
  from the actual test run. Do not present a report as proof of containment if
  the fingerprint says the backend was not isolating.
- The strategy selector is advisory. A plausible rationale is not evidence; the
  delivery gate still requires a passing test.

## Known limitations (honest)

- **seccomp is a denylist, only on x86_64 Linux.** It blocks a curated set of
  escape and attack-surface syscalls, not every unused syscall. An allowlist is
  stronger but breaks more ordinary programs; it is a future VM/container
  profile. On other architectures the report says `seccomp=False`.
- **No Landlock enforcement yet.** Landlock ABI detection is reported, but a
  per-task filesystem policy is not applied. bubblewrap's mount namespace is the
  current filesystem boundary.
- **Shared kernel.** A kernel exploit could escape a namespace sandbox. Use a VM
  backend for highly suspicious samples.
- **No cgroup v2 enforcement.** cgroup v2 detection is reported, but process
  count and memory rely on RLIMIT and PID namespaces.
- **Static parsers run in-process.** The pure-Python parsers are bounded and
  exception-safe, but they share the host interpreter. Ghidra and optional
  heavy parsers also run on the host.
- **Headless Chromium, when enabled, runs on the host** with `--no-sandbox`
  inside its own process. Do not enable it for anonymous public input on a
  shared machine.
- **Symlinked targets are refused by the agent intake.** The server analysis
  endpoint resolves a symlink and then applies the regular-file size cap.
- **Single access token, no per-user accounts or quotas.** Multi-tenant
  isolation is an M3 feature.
- **The sandbox may be unavailable on PaaS.** Then execution is refused, not
  silently run on the host. In that case verification cannot pass and the
  artifact is withheld.
- **Verification is only as good as the declared inputs.** A passing test proves
  the listed cases, not every possible input. Captured corpora help, but they are
  still a sample. A corpus is keyed by target SHA-256; if the original changes,
  capture it again.
- **A passing corpus can still be weak.** `assess_test_strength` mutates the
  candidate and reports whether the corpus detects breakage. A low mutation
  score means the tests are weak, not that the change is wrong. Delivery remains
  gated on the behavioral proof.
- **Benchmark results are a sample, not a certificate.** The benchmark now has a
  held-out split and false-verification/refusal metrics, but a high score does
  not prove general engineering capability.
- **Checkpoints are not a backup.** They live beside the workspace and are
  pruned by the operator, not by ReverseAI. Restore refuses unsafe archive
  members, but it is not a substitute for version control.
- **The replay recipe is not a proof by itself.** It reproduces the declared
  cases. Read the report first, then run it.
- **Discovery heuristics can be wrong.** A string or symbol is a lead, not a
  vulnerability, an undocumented API, or a hidden feature. The next step is an
  experiment, not a claim.
- **The world model is only as complete as its inputs.** Unmodeled components
  appear as unknowns; do not treat the twin's prediction as a deployment result.
- **The foundry and skill learner do not self-deploy.** They compare and record;
  a human still decides. Cross-customer knowledge transfer is not enabled.

## Reporting

Security issues in ReverseAI itself: open a private advisory on the repository.
Do not file public issues with working exploit details.
