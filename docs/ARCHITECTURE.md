# ReverseAI: Architecture

ReverseAI is an engineering platform with an AI agent at its center. The model
is the engineer; the analysis tools are its instruments; the sandbox is its
workshop. Reasoning is deliberately separated from execution, and execution is
deliberately separated from the host.

## Layers

```
┌──────────────────────────────────────────────────────────────────────┐
│ Interface        CLI · mobile-first PWA · SSE event stream            │
├──────────────────────────────────────────────────────────────────────┤
│ Agent            orchestrator · conversation · registry · mediator    │
│                  evidence · job · narrative · templates · memory      │
│                  skills · research · routines · pricing · modify engine│
├───────────────┬───────────────────────────────┬──────────────────────┤
│ Providers     │ Tools                         │ Durable state        │
│ deepseek      │ analysis · execution ·        │ Job store · events   │
│ openai-compat │ modification · coding ·       │ conversations ·      │
│ anthropic     │ memory · research · delegate  │ artifacts · memory   │
│ ollama/mock   │ skills · routines             │ routines · feedback  │
├───────────────┴───────────────┬───────────────┴──────────────────────┤
│ Analysis core (core/)         │ Sandbox lab (sandbox/)               │
│ identify · pe · elf · macho   │ policy · factory · bwrap · subprocess│
│ strings · disasm · heuristics │ qiling (optional)                    │
│ diff · models                 │                                      │
├───────────────────────────────┴──────────────────────────────────────┤
│ Verification (verify/) · Modification (modify/) · Clone (clone/)      │
│ strategy selector · planner · blast radius · behavioral tests ·       │
│ durable corpora · replay · repair loop · signed report                │
│ Intelligence: world · discovery · science · causal · twin · design ·  │
│ product · proof · orchestration · learning · adapters · extensions    │
│ Checkpoints · CFG · Decompile · Mobile · OCR · Bench                  │
├──────────────────────────────────────────────────────────────────────┤
│ Security: validation · limits · archive safety · SSRF-safe net ·      │
│ capability policy · approvals · action gate · optional vault          │
└──────────────────────────────────────────────────────────────────────┘
```

## Request flow

1. **Intake.** `security.validate.read_target` enforces size caps and refuses
   symlinks. A `Conversation` gets a persistent workspace under the store when
   it is created by the server.
2. **Plan.** The template and target shape a short plan. The server emits
   `start` and `plan` events.
3. **Reason.** The provider receives the system prompt, template addendum,
   memory context, skill list, conversation, and tool specs.
4. **Act.** Every tool call goes through `ToolMediator`: permission ceiling,
   optional confirmation, dispatch, exception containment, audit entry. The
   server emits a natural `reason` event before the result.
5. **Observe.** Tools append `Finding`s at the right tier. Research appends
   sources. The conversation tracks sources and artifact metadata.
6. **Model and discover.** The agent can build a world model and engineering
   graph, ask it questions, and discover ranked opportunities. Each opportunity
   points to evidence and a falsifiable next step; it is not permission to act.
7. **Choose, plan, implement.** For a change request, the engine scores the
   five strategies from the analysis and the goal, recommends or accepts a mode,
   identifies the likely components, estimates the blast radius, and asks a
   clarifying question when the request is ambiguous. `plan_and_modify` then
   runs the smallest strategy that fits through the existing executors.
8. **Experiment and simulate.** Hypotheses are tested with predictions and
   controlled observations; causal claims require explicit mechanisms; the twin
   names what is simulated and what must be tested live.
9. **Snapshot and locate.** Before a write, the workspace is checkpointed so
   the change is reversible. The agent can review a bounded diff or restore the
   snapshot. Control-flow analysis and the readiness preflight give it a map and
   an honest answer about whether the target can run here.
10. **Verify before delivery.** If a binary modification exists and no passing
   behavioral test is recorded for this turn, the delivery gate runs
   `verify_modification`. A failure can feed a bounded repair loop; a missing
   expectation is a refusal, not a pass. A scoped change also runs regression
   cases over the untouched behavior. Captured corpora can be loaded with
   `use_corpus`. A site bundle is delivered without a native execution test and
   marked unobtrusively as such.
11. **Replay.** The signed report includes target and artifact hashes and a
   command that reproduces the verification with `reverseai verify`, without a
   model. `reverseai report verify` checks the signature.
12. **Stream + persist.** Every event is appended to
   `<store>/events/<job>.jsonl`; the SSE endpoint replays from `?after=N` and
   then tails the log. Conversation state is saved to
   `<store>/conversations/<cid>.json` after each turn.
13. **Conclude.** The final answer, evidence summary, sources, usage, mode,
   strategy, plan, and artifact meta are streamed and saved as a `Job`.
   Unverified artifacts are withheld. `GET /jobs/<id>/report(.html)` builds a
   signed report on demand from the saved record, including the sandbox
   environment fingerprint and the replay recipe.

## Key contracts

- **`core.models.AnalysisReport`**: JSON-serializable truth about a binary.
- **`agent.tools.Tool`**: name + JSON-Schema parameters + permission tier + run.
- **`agent.providers.base.LLMProvider`**: `chat(messages, tools) -> LLMResponse`.
  The only seam to the model.
- **`sandbox.base.Sandbox`**: `run(argv, policy) -> ExecResult` + isolation level.
- **`agent.job.Job`**: the durable record of a turn.
- **`agent.memory.MemoryStore`** and **`routines.RoutineStore`**: small,
  human-editable JSON stores with atomic writes.
- **Event stream**: `start`, `plan`, `step`, `reason`, `assistant`,
  `tool_result`, `source`, `finding`, `verification_plan`,
  `verification_attempt`, `verification_repair`, `verification`,
  `delivery_blocked`, `final`, `error`.
- **Verification contracts**: `verify/difftest.InputCase` and `DiffReport`,
  `verify/repair.RepairLoop` / `RepairResult`, `verify/corpus.CorpusStore`,
  `verify/replay.replay_record`, and the signed report built from a serialized
  `Job`.
- **Security contracts**: `security.capabilities.CapabilityPolicy` (is the
  feature allowed?), `security.approvals.ApprovalLedger` (did a human approve
  this exact action?), and `security.gate.ActionGate` (both, plus an audit row).
- **Intelligence contracts**: `WorldModel` / `EngineeringRecord`,
  `Opportunity`, `Hypothesis` / `Experiment`, `CausalGraph`, `TwinSimulation`,
  `ProofPackage`, `CapabilityRecord`, `Mission`, and `ToolManifest`. They are
  plain JSON-serializable structures with provenance, not hidden state.

## Durable state

```
<store>/
  job_*.json            one record per turn
  events/*.jsonl        replayable SSE log
  conversations/*.json  messages, evidence, target, workspace, sources
  workspaces/<cid>/     persistent per-conversation scratch space
  checkpoints/          workspace snapshots + manifests
  corpora/<sha>.json    captured original behavior by target hash
  artifacts/            delivered files keyed by job id
  memory.json           long-term notes
  world.json            world model / engineering graph for a job
  proof/               proof.json + PROOF.md for a delivered change
  routines.json         scheduled tasks
  skills/*.md           optional playbooks
  feedback.jsonl        thumbs up/down
```

The event log is the source of truth for a live stream; the job record is the
source of truth for a finished turn. A reload can reattach to the first and a
restart can restore the second.

## Security boundaries

- The model never gets raw host access; it requests tools.
- Untrusted code runs only in the sandbox; execution is refused when no
  isolating backend exists. bubblewrap applies namespaces, capability dropping,
  and an x86_64 seccomp denylist; the report states what was applied.
- Writes are checkpointed first; restore refuses unsafe archive members.
- High-risk capabilities require a capability opt-in and, for irreversible
  actions, a live scoped approval. Both are audited.
- Server paths are allowlisted when auth is enabled.
- Research and clone fetch only public hosts, validate every redirect, and cap
  response size.
- Previewed/cloned pages run in an opaque-origin iframe.
- Headless browser rendering is opt-in; Ghidra is documented as a host parser.

## Extension points

| Next capability | Where it plugs in |
|---|---|
| MCP client | a new tool namespace + mediator permissions |
| Hooks | a policy layer around mediator dispatch |
| Docker workstation | a new sandbox/desktop backend + preview bridge |
| Telegram | a long-poll bridge around `RunManager` |
| Object storage | a `JobStore` backend |
| In-house model | a new `LLMProvider` |
| More parsers | `core/` plus an analysis tool |
| More specialists | `agent/templates.py` |

## Design rules

- The core must import and run on a clean stdlib install.
- A capability ships with a test and an honest limitation note.
- Optional heavy libraries enhance, never gate, the core.
- Keep `AnalysisReport`, `Tool`, `LLMProvider`, and `Sandbox` stable; they are
  the cross-layer contracts.
