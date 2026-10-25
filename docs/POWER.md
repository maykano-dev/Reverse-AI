# What a powerful AI company would enable

This is the honest answer to a broad question: if ReverseAI were the kernel of a
serious AI company, what would it be allowed to do? The answer is not "everything
the model can imagine." It is a layered capability system where each layer has a
different authority, a different containment boundary, and a different audit
trail.

The useful mental model is **authority, not features**:

```
observe → analyze → simulate → modify → execute → transact → control a real system
```

The further right you go, the more the product must earn the right to act.

## The layers

| Layer | What it enables | Containment | Current status |
|---|---|---|---|
| **1. Read** | Parse a binary, page, archive, repo, or dataset. Build a truthful model. | Pure in-process parsers; size limits; no execution. | **Built** |
| **2. Observe** | Run code and compare behavior across inputs. | bubblewrap namespaces, seccomp denylist, no network, RLIMITs. | **Built** |
| **3. Prove** | Turn observations into a reproducible, signed claim. | Sandbox-only execution; evidence tiers; signed reports. | **Built** |
| **4. Modify** | Change bytes, resources, components, or source; rebuild; reimplement. | Writes land on copies; checkpoints; verified-delivery gate. | **Built** |
| **5. Plan at scale** | Map control flow, call graphs, blast radius, and a long-horizon plan. | Bounded analysis; no execution; explicit uncertainty. | **Built (bounded)** |
| **6. Operate** | Use a browser, a build farm, a VM, a cluster, or a live desktop. | Separate backend, network policy, resource quotas, approvals. | **Partial** |
| **7. Transact** | Buy a domain, pay an invoice, sign a contract, move money. | Capability opt-in + scoped human approval + audit + idempotency. | **Primitives only** |
| **8. Control** | Act on a real system continuously: remote support, incident response, a production agent. | Hardware-backed identity, least privilege, human takeover, kill switch, full audit. | **Deliberately absent** |

A company that skips from layer 3 to layer 8 is not powerful. It is one incident
away from being untrustworthy.

The concrete build ledger for this layer is
[`INTELLIGENCE_ROADMAP.md`](INTELLIGENCE_ROADMAP.md). It marks what is built,
what is a foundation, and what is deliberately not claimed.

## What is already enabled

- **Autonomous reverse engineering.** Read a real binary, choose a strategy,
  plan the change, implement it on a copy, and prove the result with a behavioral
  test. Unverified artifacts are withheld.
- **Durable proof.** Behavioral corpora, differential regression, signed reports,
  replay recipes, and a model-free `reverseai verify` command.
- **A reversible workspace.** Checkpoints before writes, bounded diff review,
  conservative restore.
- **A hardened host boundary.** bubblewrap namespaces, capability dropping, a
  seccomp denylist, resource limits, no network, and an honest environment
  fingerprint in every report.
- **A real permission model.** Tools have tiers; the mediator enforces them; the
  agent cannot grant itself authority.
- **A capability policy.** Dangerous features are denied by default, and a future
  feature must pass a capability switch plus a live, scoped approval.

## What is enabled but gated

These exist as primitives, not products:

- **Encrypted vault.** Optional Fernet + PBKDF2, mode 0600, deny-by-default. It
  stores secrets; it does not spend them.
- **Approval ledger and action gate.** A human can approve one action, for one
  scope, for a few minutes, once. The gate audits the decision.
- **Foreign-platform analysis.** A PE or Mach-O can be analyzed anywhere. It is
  only *executed* when a matching host or a configured emulator/VM exists.
- **Browser and decompiler integrations.** Available, but opt-in and documented
  as host-side tools rather than sandboxed ones.

## What is deliberately absent

These are the "unbuildables" in the sense that they should not be built as a
side effect of a feature sprint:

- **A live desktop with take-over.** It needs a VM/container boundary, a
  keyboard/mouse injection channel, a recording policy, and a human handoff.
- **Telegram or any remote command channel.** It needs pairing, replay
  protection, a signed command envelope, an allowlist, and a kill switch.
- **Payment execution.** It needs a real ledger, idempotency keys, spend limits,
  a human approval for every irreversible action, and a reconciliation process.
- **Persistent multi-agent authority.** It needs per-agent identity, budgets,
  isolation, and a way to revoke authority.
- **MCP servers and hooks.** Both execute third-party code or configuration.
  They need a protocol client, per-server permissions, and prompt-injection
  defenses that treat server output as data.
- **Multi-tenant accounts and quotas.** They need per-tenant storage, isolation,
  metering, and abuse controls, not just a bearer token.

Each one is a product with its own threat model. The right move is to build the
boundary first, then the feature. This repository now has the boundary pieces:
capability policy, approvals, action gate, audit log, vault, checkpoints, signed
reports, and a sandbox fingerprint.

## The most powerful thing to build next

Not a bigger model. A **closed loop that cannot lie**:

1. **A larger verified corpus.** Capture behavior from many targets, not just the
   inputs the model chose.
2. **A benchmark that scores only verified outcomes.** Pass rate, repair success,
   regression rate, cost per verified change, time to verified change.
3. **A dataset of verified traces.** Every trace has a reproducible proof and a
   license. This is the asset a model company actually needs.
4. **A routing layer.** Send easy analysis to a small local model, hard reasoning
   to a frontier model, and never let either one bypass the gate.
5. **An operator console.** See what the agent is doing, approve the irreversible
   steps, revoke authority, and replay any decision.

That is how a powerful AI company compounds: it turns every verified change into
a reusable asset and every failure into a stricter boundary.

## The rule

> A capability is not enabled because the model can do it. It is enabled because
> the system can contain it, prove it, and undo it.

ReverseAI's code follows that rule. The rest of this page is a map of where each
piece lives.

## Where the pieces live

| Concern | Module |
|---|---|
| Capability switches | `security/capabilities.py` |
| Human approvals | `security/approvals.py` |
| Action gate + audit | `security/gate.py` |
| Encrypted vault | `security/vault.py` |
| Sandbox policy + seccomp | `sandbox/policy.py`, `sandbox/seccomp.py` |
| Execution readiness | `sandbox/readiness.py` |
| Behavioral corpora | `verify/corpus.py` |
| Replay + signed reports | `verify/replay.py`, `verify/report.py` |
| Checkpoints + restore | `checkpoints.py` |
| Control-flow maps | `core/cfg.py` |
| Strategy + plan | `modify/strategy.py`, `modify/planner.py` |
| Delivery gate | `agent/conversation.py` |
