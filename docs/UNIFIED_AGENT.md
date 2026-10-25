# The unified agent: what was taken from where

ReverseAI is not a reimplementation of six separate products. It is one engine,
one sandbox, one UI, and one evidence model, with the useful ideas from several
agent products folded into it. This page is the honest map: what is implemented,
what is partial, and what is deliberately deferred.

## The essence we kept

Every product below converges on the same loop:

```
goal → plan → reason → use tools → observe → remember → verify → deliver
```

ReverseAI already had the loop, the sandbox, and evidence tiers. The 0.2 work
made the loop **visible**, **durable**, **personal**, and **mobile**.

## Feature map

| Capability | Source idea | Status | Where it lives |
|---|---|---|---|
| Plan before acting | Claude Code, OpenCode, Grok Bot | **Implemented** | `agent/narrative.py`, `plan` / `reason` SSE events, Steps UI |
| Visible chain of thought | Claude Code, prompt-kit | **Implemented** | `agent/narrative.py`, `static/style.css` (`.cot`, `.thinking-bar`) |
| Tool call cards with real output | OpenCode, prompt-kit | **Implemented** | `tool_result` events, `.tool-card` |
| Permission tiers + audit | Claude Code, OpenCode | **Implemented** | `agent/mediator.py`, `agent/tools.py` |
| Read / execute / write modes | Claude Code | **Implemented** | composer selector, `server/runs.py` |
| Specialist agents | Xiryn, Claude Code subagents | **Implemented (delegate)** | `agent/templates.py`, `DelegateTool`, `delegate` |
| Agent templates / squads | Xiryn | **Partial** | 8 templates and one-shot delegation; no persistent squads |
| Long-term memory | Xiryn, Claude Code | **Implemented** | `agent/memory.py`, Memory panel, `remember` / `recall` |
| Skills / playbooks | Claude Code, OpenCode | **Implemented (local markdown)** | `agent/skills.py`, `REVERSEAI_SKILLS`, `read_skill` |
| Web research with sources | Xiryn | **Implemented** | `agent/research.py`, `web_search` / `web_read`, Source cards |
| Durable turns / reattach | Xiryn | **Implemented** | JSONL event log, `?after=N`, saved conversations |
| Routines / schedules | Xiryn | **Implemented** | `routines.py`, scheduler, Routines panel |
| Usage and budget | Xiryn | **Implemented (estimates)** | `agent/pricing.py`, `/usage`, `REVERSEAI_MONTHLY_BUDGET` |
| Feedback | Xiryn, prompt-kit | **Implemented** | `/feedback`, feedback bar |
| Desktop notifications | Xiryn | **Implemented** | Notification API, settings toggle |
| Speech input / spoken replies | Xiryn | **Implemented (browser)** | Web Speech API |
| Local models | Xiryn | **Implemented** | Ollama / OpenAI-compatible provider |
| PWA / mobile first | Xiryn | **Implemented** | manifest, service worker, responsive CSS |
| Code blocks with header + copy | prompt-kit | **Implemented** | markdown renderer, `.codeblock` |
| Source cards | prompt-kit | **Implemented** | `.source` |
| Loaders / thinking bar | prompt-kit | **Implemented** | `.loader`, `.thinking-bar` |
| Feedback bar | prompt-kit | **Implemented** | `.feedback` |
| Scroll button | prompt-kit | **Implemented** | `#scrollBtn` |
| Unlimited-OCR | Baidu | **Implemented (adapter)** | `ocr/engine.py`, `REVERSEAI_OCR_URL` |
| Artifact naming | user request | **Implemented** | `naming.py`, artifact cards |
| Real cancellation | Claude Code, Xiryn | **Implemented** | `/jobs/:id/cancel`, `stop_event` |
| Verified delivery gate | project principle | **Implemented** | `verify_modification`, `agent/conversation.py` gate |
| Bounded repair loop | Claude Code, Xiryn | **Implemented** | `verify/repair.py`, model repair callback |
| Differential testing | new / testing practice | **Implemented** | `verify/difftest.py`, `differential_test` |
| Signed verification report | new | **Implemented** | `verify/report.py`, `/jobs/:id/report(.html)` |
| Strategy selection | new | **Implemented** | `modify/strategy.py`, `choose_modification_strategy` |
| Modification planning | new | **Implemented** | `modify/planner.py`, `plan_and_modify` |
| Three product modes | product spec | **Implemented** | Direct / Reconstruction / Modernisation |
| Blast-radius scoping | new | **Implemented** | planner components + regression cases |
| High-risk capability gate | new | **Implemented** | `security/capabilities.py`, deny by default |
| Behavioral corpora | new | **Implemented** | `verify/corpus.py`, `capture_behavior_corpus`, `use_corpus` |
| Model-free replay | new | **Implemented** | `verify/replay.py`, `reverseai verify`, replay recipe |
| Checkpoints / undo | Claude Code | **Implemented (workspace)** | `checkpoints.py`, `create/restore_workspace_checkpoint` |
| Diff review | Claude Code | **Implemented (workspace + structural)** | `review_workspace_changes`, `diff_modified` |
| Control-flow graph | new | **Implemented (bounded)** | `core/cfg.py`, `build_control_flow_graph` |
| Execution readiness | new | **Implemented** | `sandbox/readiness.py`, `readiness` |
| seccomp host hardening | new | **Implemented (x86_64 denylist)** | `sandbox/seccomp.py`, bubblewrap `--seccomp` |
| Approvals + action gate | new | **Implemented** | `security/approvals.py`, `security/gate.py` |
| Encrypted vault | Xiryn | **Implemented (optional primitive)** | `security/vault.py`; no payment execution |
| Engineering world model | new | **Implemented** | `intelligence/world.py`, `build_world_model` |
| Autonomous discovery | new | **Implemented (static + experiment leads)** | `intelligence/discovery.py`, `discover_opportunities` |
| Scientific experiments | new | **Implemented (runner injected)** | `intelligence/science.py`, `form_hypotheses` |
| Causal reasoning | new | **Implemented (explicit mechanisms)** | `intelligence/causal.py` |
| Digital twin | new | **Implemented (contract simulation)** | `intelligence/twin.py`, `simulate_change` |
| Architecture search | new | **Implemented (scored, benchmark callback)** | `intelligence/design.py`, `search_architectures` |
| Algorithm optimization | new | **Implemented (equivalence + measured)** | `intelligence/design.py` |
| Tool forge | new | **Implemented (sandbox-tested)** | `intelligence/forge.py`, `forge_tool` |
| Spec-to-product | new | **Implemented (plan + acceptance)** | `intelligence/product.py`, `plan_product` |
| Software from behaviour | new | **Foundation** | `BehaviorContract`; replacement generation is not bundled |
| Proof-carrying artifact | new | **Implemented** | `intelligence/proof.py`, `build_proof_package` |
| Independent verifier | new | **Implemented** | `IndependentVerifier` |
| Confidence calibration | new | **Implemented (no small-sample percentages)** | `ConfidenceCalibrator` |
| Model router | new | **Implemented** | `intelligence/orchestration.py`, `select_model` |
| Universal tool protocol | new | **Implemented** | `ToolManifest`, `export_tool_manifests` |
| Capability discovery | new | **Implemented** | `CapabilityMap`, `capability_map` |
| Mission control / economy | new | **Implemented (plans and budgets)** | `MissionPlanner`, `AutonomousEconomy` |
| Intelligence foundry | new | **Implemented (baseline + holdout)** | `IntelligenceFoundry` |
| Verified skill learning | new | **Implemented** | `SkillLearner` |
| Domain adapters | new | **Foundation** | hardware, robotics, CAD, network, security |
| Computer operator | Xiryn | **Boundary only** | no live input or remote listener |
| Extension registry | new | **Foundation** | signed manifests, no auto-execution |
| MCP servers | Claude Code, OpenCode | **Deferred** | needs a protocol client and permission model |
| Hooks (pre/post tool) | Claude Code | **Deferred** | needs an operator policy and sandboxing |
| Computer use / live desktop | Xiryn, OpenClaw | **Deferred** | denied by capability policy; needs Docker workstations, VNC, and a new threat model |
| Take over / hand back | Xiryn | **Deferred** | depends on workstations |
| Telegram remote control | Xiryn | **Deferred** | denied by capability policy; needs a bot bridge and pairing |
| Payment execution | Xiryn | **Deferred (deliberately)** | approval primitive exists; the processor and ledger do not |
| Persistent multi-agent squads | Xiryn | **Partial** | delegation works; persistent authority is denied by capability policy |
| MCP / hooks | Claude Code, OpenCode | **Deferred** | denied by capability policy; need a protocol/permission design |
| Hosted multi-tenant accounts | product layer | **Deferred** | single token now; auth/quotas later |

## Why some things are deferred

- **Workstations and live desktops** are a different product surface: containers,
  VNC, browser control, and a much larger threat model. The sandbox already runs
  untrusted code; adding a desktop should be a backend, not a hack.
- **MCP and hooks** need a protocol implementation and a permission design that
  survives prompt injection. Shipping them half-done would weaken the mediator.
- **A vault and payment flows** should not be added to an unaudited local app.
  The vault primitive and approval gate are in place; the payment processor is
  not, and the README is explicit about that.
- **MCP and hooks** remain denied until they have a permission model that treats
  every server and hook as hostile code, not as configuration.
- **Multi-tenant accounts** are an M3 concern: token auth and path allowlists are
  in place, but quotas, object storage, and per-tenant isolation are not.

## The rule for new features

A capability is not "added" until it has:

1. a tool or backend with a clear permission tier,
2. a test that demonstrates the behavior (not just the happy-path build),
3. an honest note about what it does not protect against.

That rule is why this page separates "implemented" from "partial" and "deferred".
