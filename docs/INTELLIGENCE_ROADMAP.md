# ReverseAI Intelligence Roadmap

This is the build ledger for the "discover what nobody asked for" program. It
turns a very large ambition into ordered, testable layers. Each item is marked
with its real state, not its aspiration.

Status key:

- **built** — code + offline tests + an honest limitation note.
- **foundation** — stable data model / interface exists; the domain adapter or
  external simulator is not bundled.
- **deferred** — deliberately not implemented until the boundary exists.

The rule for every item is the same as the rest of ReverseAI: observed evidence
beats a plausible story, and a capability is not "added" until it can be
contained, verified, and undone.

## Phase 0 — the ledger

- [x] Create this roadmap and keep it current.
- [x] Define the shared contracts: world model, engineering graph, hypothesis,
      experiment, opportunity, proof package, mission, capability record.
- [x] Keep the core importable with zero required dependencies.
- [x] Add offline tests for every new layer.

## Phase 1 — understand the system, not just the file

- [x] **Engineering World Model**: components, relationships, data flow,
      dependencies, state, failure conditions, user interactions, unresolved
      questions, provenance, confidence.
- [x] **World-model persistence**: JSON store, merge, query, invalidate.
- [x] **Engineering Graph**: requirements → components → experiments →
      modifications → tests → evidence → decisions.
- [x] **Project Memory**: episodic, semantic, procedural, causal, project,
      temporal, and evaluation records with provenance.
- [x] **Graph queries**: unverified requirements, weak-evidence components,
      orphaned decisions, stale claims, and next-best tests.
- [x] **World-model tool**: `build_world_model`, `query_world_model`.
- [x] **Causal Reasoning Engine**: intervention and counterfactual queries over
      an explicit causal graph; baseline vs intervention; no correlation-only
      claim is labeled causal.
- [x] **Digital Twin Engine**: simulate a proposed change, identify affected
      components, predicted failures, and the parts that remain unverified.
- [x] **Hybrid simulation plan**: simulated vs live-test vs unknown.

## Phase 2 — discover what nobody asked for

- [x] **Autonomous Discovery Engine**: undocumented features, hidden
      functionality, inefficient operations, architectural weaknesses,
      undocumented APIs/dependencies, unlockable capabilities, and hypotheses
      worth testing.
- [x] **Opportunity ranking**: impact, confidence, effort, risk, evidence,
      proposed action, approval requirement.
- [x] **Discovery mission planning**: ordered investigations with expected
      information gain and stopping conditions.
- [x] **Scientific Experiment Engine**: hypothesis → experiment design →
      prediction → controlled run → compare → update → repeat.
- [x] **Evidence tiers for science**: established fact, likely explanation,
      untested hypothesis, unknown.
- [x] **Debate / competing hypotheses**: adversarial review and discriminating
      experiments, not agent voting.
- [x] **Hypothesis tooling**: `form_hypotheses`, `design_experiment`,
      `run_experiment`, `review_hypotheses`.
- [x] **Experiment safety**: target code only through the sandbox; refusing when
      containment is unavailable.

## Phase 3 — invent better solutions

- [x] **Autonomous Architecture Search**: candidate architectures, measurable
      objectives, constraints, benchmark callback, Pareto front, recommendation
      with trade-offs.
- [~] **Algorithm Optimization**: benchmark, equivalence check, and measured
      speed/memory comparison are built; automatic algorithm synthesis is not
      bundled. The optimizer compares candidates supplied by the agent.
- [x] **Tool and Instrument Creation**: forge a small tool, test it in the
      sandbox, keep a manifest, and reuse it only after it passes.
- [~] **Simulation Factory**: generates a provisional environment spec with
      assumptions and omissions; it does not run a physics or network simulator.
- [x] **Representation Search**: compare candidate representations with a
      benchmark callback and keep the one that measurably helps.
- [x] **Cross-domain analogy**: structural mapping is a hypothesis to test, not
      a conclusion.

## Phase 4 — create software from intent and behaviour

- [~] **Specification-to-Product Engine**: requirements, acceptance criteria,
      constraints, non-goals, threat model, and phased plan are built. Full
      multi-platform code generation and deployment are not bundled.
- [x] **Requirement change handling**: add/remove/change requirements without
      losing prior decisions.
- [~] **Any-language engineering**: detects language/build system and explains
      trade-offs. It does not install or run every toolchain.
- [~] **Software from Behaviour**: observable-contract evaluation and an
      underdetermination plan; a full replacement generator is not bundled.
- [x] **Proof-Carrying Artifact**: original/modified hashes, tools, versions,
      tests, before/after measurements, limitations, reproduction, signature.
- [x] **Independent Verification Engine**: separate verifier, acceptance
      criteria, prohibited changes, regression and security checks.
- [x] **Regression Prevention**: promote a confirmed case into the durable
      corpus.
- [x] **Confidence Calibration**: no invented percentages; report only
      calibrated or explicitly qualitative confidence.

## Phase 5 — orchestrate models, tools, and projects

- [x] **Model Intelligence Router**: capability, latency, cost, privacy, local
      vs remote, previous performance; fallback; independent reviewer rule.
- [x] **Universal Tool Protocol**: manifests with permissions, inputs, outputs,
      resource limits, security boundaries, and version.
- [x] **Capability Discovery System**: measured success rate, failure modes,
      cost, time, required tools, stuck detection, independent verification.
- [x] **Mission Control**: objective, constraints, budget, deadline, phases,
      checkpoints, approvals, cancellation, recovery.
- [x] **Autonomous Economy**: expected value of an investigation vs its cost;
      stop when marginal value is too low.
- [x] **Trust Engine**: risk classification, reversibility, approval policy,
      audit trail.
- [x] **Intelligence Foundry**: baseline → candidate → holdout → benchmark →
      approve/rollback, with a guard against test memorization.
- [x] **Universal Learning Engine**: record a verified skill, test it on a
      holdout, version it, and mark it stale when the environment changes.
- [x] **Generalization Engine**: compare training cases to an unseen holdout
      and flag memorization as a failure of generalization.
- [~] **Organizational memory**: scoped project memory and temporal records
      are built; ingesting an authorized enterprise corpus is an adapter.
- [~] **Cross-project learning**: scopes prevent leakage and analogy is treated
      as a hypothesis; a shared cross-customer knowledge base is not built.
- [~] **Self-improving flywheel**: observe → record → propose → benchmark →
      holdout → human approve is represented. Automatic self-deployment is not.
- [~] **Extension Registry**: local, declared capabilities with permissions and
      a security review state.
- [x] **Debate / review surface**: competing explanations and a human-readable
      decision record.

## Phase 6 — the domain adapters (foundation, not fake products)

- [~] **Hardware / firmware adapter contract**: firmware inventory, entropy,
      architecture, probable update path; no oscilloscope or PCB claim.
- [~] **Robotics adapter contract**: sensors, actuators, control loop,
      calibration hypotheses; simulation-only until a simulator is connected.
- [~] **CAD / mechanical adapter contract**: geometry and constraint slots; no
      geometry kernel bundled.
- [~] **Network / infrastructure adapter contract**: topology, protocol,
      dependency and drift hypotheses; live changes require approval.
- [~] **Security intelligence adapter**: threat model, dependency/supply-chain,
      secret exposure, permission review, patch verification.
- [~] **Universal Computer Operator boundary**: a workspace/VM/approval
      interface; no live desktop listener or input injection is enabled.
- [~] **Marketplace boundary**: signed extension manifests, compatibility and
      test requirements; no third-party code is auto-trusted.

## Phase 7 — research bets, not promises

- [x] **Intelligence Compiler**: intent → measurable spec → executable plan.
- [x] **Reality Engine**: prediction / simulation / observation / unknown are
      distinct provenance classes.
- [x] **Counterfactual Engine**: explicit intervention, assumptions, and
      uncertainty.
- [x] **Universal Memory Fabric**: multiple memory classes with access scopes.
- [x] **Knowledge Translator**: analogy as a testable transfer hypothesis.
- [x] **Intelligence Compression**: route routine work to cheaper models/tools;
      measure quality, not just cost.
- [x] **Reconstruction from evidence**: executable + screenshots + logs + docs +
      behaviour; report underdetermination honestly.
- [x] **Self-explaining failure**: classify failure as information, plan, tool,
      assumption, compute, or model limitation.
- [x] **Know when humans are better**: identify the exact human decision,
      explain choices, continue the rest.
- [~] **Autonomous research laboratory**: research plans, competing
      explanations, experiment reports, and limitations; external literature
      retrieval is delegated to the existing research tools.
- [ ] **Digital civilization lab**: controlled multi-agent research environment.
      This is a research program, not a shipped feature.
- [ ] **New scientific theory / new representation / self-developed
      representations**: explicitly research bets. The platform records
      hypotheses and experiments but does not promise discovery.
- [x] **Moonshot ledger**: theoretical directions are documented, not sold as
      shipped.

## What is deliberately not claimed

These have a contract or a plan, but not a working domain product:

- No physical hardware inspection, safe-flash procedure, PCB analysis, or
  oscilloscope integration. The hardware adapter only reads the firmware image.
- No robot actuation, safety certification, or physics engine. Robotics is
  simulation-only until a simulator and a human safety observer are connected.
- No CAD geometry kernel, manufacturing validation, or mechanical simulation.
- No live network configuration change. A network experiment needs an isolated
  lab and an approval before production.
- No live desktop listener, remote command channel, payment processor, or
  third-party marketplace hosting. The boundaries and approval primitives exist;
  the dangerous surfaces do not.
- No self-modification, self-training, or self-deployment. The foundry compares
  candidate configurations against a baseline and a holdout; a human still
  approves a deployment.

## Non-negotiables

- [x] No target execution outside `reverseai/sandbox`.
- [x] No delivery without a passing behavioral test and a signed report.
- [x] No claim of "proof" from ordinary testing.
- [x] No invented confidence percentages.
- [x] No cross-customer leakage in memory or learning.
- [x] No irreversible action without a capability switch, a scoped approval,
      and an audit row.
- [x] No self-modification, self-training, or self-deployment without the
      controlled pipeline and a human approval.

## How this is tested

```bash
python3 -m unittest discover -s tests
```

The intelligence layer has its own offline suites:

```bash
python3 -m unittest tests.test_intelligence_world -v
python3 -m unittest tests.test_intelligence_discovery -v
python3 -m unittest tests.test_intelligence_science -v
python3 -m unittest tests.test_intelligence_design -v
python3 -m unittest tests.test_intelligence_product -v
python3 -m unittest tests.test_intelligence_orchestration -v
python3 -m unittest tests.test_intelligence_tools -v
```

The full suite is 385 tests at the time of this ledger. Counts change; the
checklist is about coverage of the capability, not the number.

