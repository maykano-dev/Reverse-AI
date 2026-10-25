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

## Known limitations (honest)

- **No seccomp or landlock filter yet.** Namespaces and capability dropping are
  strong, but a per-task syscall allowlist is not implemented.
- **Shared kernel.** A kernel exploit could escape a namespace sandbox. Use a VM
  backend for highly suspicious samples.
- **No cgroup v2 limits.** Process count and memory rely on RLIMIT and PID
  namespaces.
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
  silently run on the host.

## Reporting

Security issues in ReverseAI itself: open a private advisory on the repository.
Do not file public issues with working exploit details.
