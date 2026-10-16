# ReverseAI — Architecture

ReverseAI is an engineering platform with an AI agent at its center. The model
is the engineer; the analysis tools are its instruments; the sandbox is its
workshop. Reasoning is deliberately separated from execution.

## Layers

```
 ┌─────────────────────────────────────────────────────────────────┐
 │ Interface            CLI today; API + web UI planned              │
 ├─────────────────────────────────────────────────────────────────┤
 │ Agent (agent/)       orchestrator loop · tool registry ·          │
 │                      mediator (policy) · evidence · job record    │
 ├───────────────┬───────────────────────────────┬──────────────────┤
 │ Providers     │ Tools (builtins)              │ Evidence/Job      │
 │ (providers/)  │ analyze/read/strings/disasm/  │ believed/observed │
 │ deepseek·mock │ run_in_sandbox/record_finding │ /verified · audit │
 ├───────────────┴───────────────┬───────────────┴──────────────────┤
 │ Analysis core (core/)         │ Sandbox lab (sandbox/)            │
 │ identify·pe·elf·strings·      │ policy · factory · backends       │
 │ disasm·models(AnalysisReport) │ (bubblewrap·subprocess·…)         │
 ├───────────────────────────────┴───────────────────────────────────┤
 │ Security (security/)   input validation · resource limits         │
 └─────────────────────────────────────────────────────────────────┘
```

## Request flow (an investigation)

1. **Intake.** `Agent.run(goal, target)` validates the target
   (`security.validate.read_target`: size caps, symlink/traversal guards) and
   opens a `Job` with an ephemeral workspace.
2. **Reason.** The orchestrator sends the system prompt + conversation + tool
   specs to the `LLMProvider`.
3. **Act.** If the model requests tool calls, each goes through the
   `ToolMediator`: permission-tier check → (optional) confirmation → dispatch →
   exception containment → audit entry. Tool results return to the model.
4. **Observe & record.** Tools append `Finding`s to the `EvidenceLog` at the
   right confidence tier. Execution happens only via `run_in_sandbox`.
5. **Conclude.** When the model replies with no tool calls, that is the final
   answer. The `Job` holds the full transcript, audit log, evidence, and usage;
   `Job.report()` renders a tier-separated summary.

## Key contracts (stable; change deliberately)

- **`core.models.AnalysisReport`** — JSON-serializable truth about a binary.
  Shared by tools, API, and (later) training-data collection.
- **`agent.tools.Tool`** — name + JSON-Schema params + permission tier + `run`.
  Adding a capability = adding a Tool; nothing else changes.
- **`agent.providers.base.LLMProvider`** — `chat(messages, tools) -> LLMResponse`.
  The only seam to the model. In-house model slots in here later.
- **`sandbox.base.Sandbox`** — `run(argv, policy) -> ExecResult` + an
  `isolation_level`. New isolation tech (qiling, qemu, gVisor) = a new backend
  registered with the factory; the agent is unaffected.

## Extension points (the roadmap, in code terms)

| Next capability | Where it plugs in |
|---|---|
| Deeper disassembly / CFG | optional capstone/angr behind `core/disasm` + a new Tool |
| Binary **modification** | new `modify/` package (LIEF-backed) + WRITE-tier tools |
| Cross-platform execution | `QilingSandbox` backend (emulation) registered with factory |
| Full-system VM | `QemuSandbox` backend for Windows/foreign-arch targets |
| Ghidra decompilation | a tool that drives Ghidra headless inside the sandbox |
| Verification/regression | a `verify/` module that diffs original vs modified behavior |
| API + jobs at scale | FastAPI over `Agent`/`Job`; Redis workers; Postgres job store |
| In-house model | a new `LLMProvider`; train on collected `Job` records |

## Design rules

- The model never gets raw host access; it only requests Tools.
- Untrusted code runs only in the sandbox, never on the host.
- Optional heavy libraries (lief/capstone/qiling/angr) enhance but are never
  required — the core must import and run on a clean stdlib install.
- Every capability ships with a test. A green build is not a working feature.
