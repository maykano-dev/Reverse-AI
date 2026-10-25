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
| MCP servers | Claude Code, OpenCode | **Deferred** | needs a protocol client and permission model |
| Hooks (pre/post tool) | Claude Code | **Deferred** | needs an operator policy and sandboxing |
| Checkpoints / undo | Claude Code | **Deferred** | would build on conversation state |
| Diff review UI | Claude Code | **Partial** | report shows structural diff, no inline review |
| Computer use / live desktop | Xiryn, OpenClaw | **Deferred** | needs Docker workstations, VNC, and a new threat model |
| Take over / hand back | Xiryn | **Deferred** | depends on workstations |
| Telegram remote control | Xiryn | **Deferred** | needs a bot bridge and pairing |
| Encrypted vault / payments | Xiryn | **Deferred (deliberately)** | high-risk; out of scope until audited |
| Persistent multi-agent squads | Xiryn | **Partial** | delegation works, shared memory is global |
| Hosted multi-tenant accounts | product layer | **Deferred** | single token now; auth/quotas later |

## Why some things are deferred

- **Workstations and live desktops** are a different product surface: containers,
  VNC, browser control, and a much larger threat model. The sandbox already runs
  untrusted code; adding a desktop should be a backend, not a hack.
- **MCP and hooks** need a protocol implementation and a permission design that
  survives prompt injection. Shipping them half-done would weaken the mediator.
- **A vault and payment flows** should not be added to an unaudited local app.
  The current README is explicit about that.
- **Multi-tenant accounts** are an M3 concern: token auth and path allowlists are
  in place, but quotas, object storage, and per-tenant isolation are not.

## The rule for new features

A capability is not "added" until it has:

1. a tool or backend with a clear permission tier,
2. a test that demonstrates the behavior (not just the happy-path build),
3. an honest note about what it does not protect against.

That rule is why this page separates "implemented" from "partial" and "deferred".
