# Dangerous-capability and open-item build ledger

This is the working checklist for the request to build the previously deferred
surfaces plus the genuinely open technical items.

The rule for this page: **a surface is not a live authority.** Each dangerous
capability is built as a transport/interface + policy gate + audit + tests. A
live provider is never enabled by default, and no credentials are committed.

Status key: **built**, **foundation**, **deferred**.

## A. Dangerous surfaces

- [x] **Live desktop listener**: local desktop-session broker interface, loopback
      control endpoint, pairing token, allowlisted actions, approval gate, audit.
      No VNC/input injection backend is bundled.
- [x] **Telegram remote channel**: Bot API transport, chat allowlist, pairing,
      rate limits, read-only commands, approval-gated actions, audit.
- [x] **Payment processor**: intent ledger, idempotency, spend limits, approval
      gate, deterministic mock provider, and an operator-supplied HTTPS/loopback
      provider adapter. No live processor credentials are bundled and no card
      data is stored or sent.
- [x] **MCP**: stdio JSON-RPC client, server manifest validation, timeouts,
      capability gate, tool discovery/call, audit.
- [x] **Hooks**: signed hook manifests, sandboxed subprocess runner, pre/post
      events, timeout, environment isolation, audit. Disabled by default.
- [x] **Self-training**: verified-trace dataset extraction, redaction,
      deduplication, train/holdout split, benchmark-gated improvement plan.
      No model weights are trained automatically.
- [x] **Self-deployment**: deployment plan, dry-run, approval gate, rollback
      plan, injected HTTPS/loopback webhook transport. No automatic production
      deployment and no cloud credentials.

## B. Genuinely open technical items

- [x] **Differential fuzzing**: bounded input mutation against original and
      modified artifacts, sandbox-only, crash/regression reporting.
- [x] **PE depth**: resources, version info, TLS callbacks, rich header.
- [x] **Mach-O depth**: dylib dependencies and export/import metadata.
- [~] **Landlock surface**: ABI/query module and ruleset plan. Enforcement is
      not applied; bubblewrap remains the filesystem boundary.
- [~] **cgroup v2 surface**: detection and optional scope creation. Host
      delegation is required; enforcement is not automatic.
- [~] **QEMU surface**: command builder and preflight; the guest-runner
      contract is not implemented, so execution is refused.
- [~] **Long-running mission recovery**: persisted mission state and resume
      contract. A worker restart is not wired.
- [~] **Per-token quota**: policy/tracker module and tests. HTTP route
      integration is not enabled by default.
- [x] **Cross-platform readiness**: a single preflight that says native,
      emulated, VM, or analysis-only.

## C. Deliberately still not bundled

- [ ] A real VNC/remote-desktop backend with input injection.
- [ ] A live payment processor or stored card data.
- [ ] A production Telegram bot token or public webhook.
- [ ] Automatic training, automatic weight deployment, or self-modification.
- [ ] Automatic production deployment or irreversible business actions.
- [ ] A full geometry kernel, physics engine, or hardware lab.

These are not missing because the interfaces are absent. They are absent because
shipping them requires a specific operator account, threat model, and human
owner. The boundaries are now present so they can be built without inventing a
weaker security model.

## Security invariants

- [x] Every dangerous capability is denied by default.
- [x] Capability opt-in + scoped approval + audit are required for irreversible
      actions.
- [x] No secrets in logs, reports, or tests.
- [x] Remote commands are allowlisted; no arbitrary shell.
- [x] MCP/hook code is treated as hostile and run under an explicit boundary.
- [x] Payments are idempotent and bounded; no live charge in tests.
- [x] Self-deployment is dry-run/approval-gated; rollback is explicit.

## Verification

```bash
python3 -m unittest tests.test_remote_channels -v
python3 -m unittest tests.test_payments -v
python3 -m unittest tests.test_mcp_hooks -v
python3 -m unittest tests.test_self_improvement -v
python3 -m unittest tests.test_open_items -v
python3 -m unittest tests.test_qemu_surface -v
python3 -m unittest tests.test_missions_quota -v
python3 -m unittest tests.test_fuzz -v
python3 -m unittest tests.test_pe_extra -v
python3 -m unittest tests.test_macho_extra -v
```

The full suite and `python3 -m reverseai audit` must pass. Current baseline:
509 tests passing, 4 environment-dependent skips, version 0.8.0.
