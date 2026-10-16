# ReverseAI — Security Model

ReverseAI ingests and executes software it does not trust. Security is not a
feature bolted on later; it is the core constraint the architecture is built
around. This document states the threat model, the trust boundaries, the
guarantees we make, and — just as importantly — the ones we do **not** yet make.

## Assets we protect

1. **The host** running ReverseAI (developer machine or server) — its
   filesystem, network, credentials, and other processes.
2. **Other jobs / tenants** — one analysis must not observe or affect another.
3. **The user's original artifact** — never mutated in place; we work on copies.
4. **Secrets** — API keys and tokens never reach logs, transcripts, or the model.

## Adversaries

- **The target binary.** Assume it is actively hostile: it may attempt sandbox
  escape, resource exhaustion, network callbacks (exfiltration / C2), host
  filesystem access, and anti-analysis behavior.
- **Prompt injection via target contents.** Strings, filenames, and metadata in
  the target may contain text crafted to manipulate the model ("ignore your
  rules, run this command"). Tool output is **data, not instructions.**
- **A buggy or over-eager model.** The agent may request dangerous actions; the
  mediator — not the model — decides what is allowed.

## Trust boundaries

```
 user (chat/CLI)  ── trusted instructions ──►  Agent orchestrator
                                                   │
                                   requests tools  │  (model output is UNTRUSTED)
                                                   ▼
                                           Tool Mediator  ◄── enforces permission tier,
                                                   │            confirmation, audit
                                       dispatches  ▼
                             Tools ──► Sandbox (untrusted code runs ONLY here)
                                           │
                        strong isolation   ▼
                                       the target binary
```

Only instructions from the **user** are authoritative. Everything observed
through a tool (binary contents, program output, filenames) is untrusted data.

## Isolation guarantees (current)

Untrusted execution goes through `run_in_sandbox`, which uses the strongest
backend the host offers. On a typical Linux host that is **bubblewrap**:

| Control | Mechanism | Status |
|---|---|---|
| No network / exfiltration | `--unshare-net` (no interfaces) | ✅ enforced + tested |
| Process isolation | `--unshare-pid --unshare-ipc --unshare-uts` | ✅ |
| Read-only system | system dirs bound `ro`; writes confined to tmpfs `/work` | ✅ tested |
| No host env / secrets | `--clearenv`, explicit minimal env | ✅ tested |
| Privilege reduction | `--unshare-user`, `--cap-drop ALL` | ✅ |
| Input injection | `--new-session` (blocks TIOCSTI) | ✅ |
| Resource exhaustion | RLIMIT cpu/mem/fsize/nofile + wall-clock timeout + process-group kill | ✅ tested |
| Lifetime | `--die-with-parent`; ephemeral workdir removed after run | ✅ |

**Hard refusal:** if a job requests untrusted execution and no isolating backend
is available (no bubblewrap + user namespaces, no container runtime, no
emulator), ReverseAI refuses to run the code rather than falling back to the
host. See `sandbox/factory.create_sandbox`.

The `ExecResult.isolation` record reports what was **actually** enforced, so
reports never overstate containment.

## Known limitations (be honest)

These are real gaps. Do not claim protection we don't have.

- **No seccomp syscall filter yet.** Namespaces + caps are strong, but a
  per-task seccomp-bpf allowlist (defense-in-depth) is not implemented. Planned.
- **Kernel attack surface remains.** Namespace sandboxes share the host kernel;
  a kernel-level exploit could escape. For maximum isolation of highly
  suspicious samples, use a VM backend (qemu) — designed, not yet wired.
- **No cgroup limits.** Process-count/memory capping relies on RLIMIT and the
  PID namespace; cgroup v2 controllers are not yet applied.
- **Static analysis parses untrusted bytes in-process.** The pure-Python
  parsers are defensive (bounded, exception-safe) but run in the host
  interpreter. Heavy third-party parsers should run in the sandbox.
- **Symlinked targets are refused** by `read_target` (conservative default).

## Secrets handling

- API keys are read from the environment (`DEEPSEEK_API_KEY`) and never logged.
- The DeepSeek provider sends only the conversation and tool specs upstream.
  **Target bytes are not sent to the model** unless a tool explicitly returns a
  slice (e.g. a hex window you requested) — keep that in mind for confidential
  binaries, and prefer a self-hosted model for sensitive work.

## Reporting

Security issues in ReverseAI itself: open a private advisory on the repository.
Do not file public issues with working exploit details.
