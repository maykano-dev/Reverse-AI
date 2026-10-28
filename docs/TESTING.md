# Testing and evaluation

This page is the evidence trail for the audit. It separates three questions:

1. **Does the code work?** — unit and contract tests.
2. **Can the proof detect a broken change?** — mutation strength.
3. **Can the agent complete real tasks?** — benchmark, with a held-out split.

## 1. Unit and contract tests

```bash
python3 -m unittest discover -s tests
python3 -m unittest tests.test_tool_contracts -v
python3 -m unittest tests.test_cli_contracts -v
python3 -m unittest tests.test_server_auth -v
python3 -m unittest tests.test_sandbox_boundaries -v
```

The tool contract suite calls every registered tool with empty arguments and
requires a `ToolResult`, never an exception. It also checks the name, JSON schema,
permission tier, narration, and UI label. This is how a broken import or a
partial-call crash is caught before a model ever sees it.

The sandbox boundary suite checks that the target cannot reach the network, read
host files, inherit host secrets, or outlive its timeout. It skips cleanly when
the host has no isolating backend.

## 2. Mutation strength

A passing test is not automatically a strong test. Run:

```python
from reverseai.verify.mutation import assess_mutations
```

or use the agent tool:

```
assess_test_strength(cases=[...])
```

The tool mutates the candidate in small, deterministic ways and checks whether
the corpus observes each mutant. It reports:

- `mutation_score`: killed / total mutants
- `killed_by`: which case detected which mutation
- `weak_cases`: cases that detected nothing
- `survived_mutations`: broken candidates the corpus would have accepted

A low score is a warning, not a delivery decision. The delivery gate remains the
authority.

## 3. Benchmark

```bash
python3 -m reverseai bench --list
python3 -m reverseai bench --split dev
python3 -m reverseai bench --split holdout --json
```

The benchmark records:

- verified task success
- regression rate
- repair success rate
- false verification rate
- appropriate refusal rate
- cost per verified task
- time per verified task
- development and held-out splits

The holdout set is for measurement, not tuning. A high development score with a
low holdout score means memorization, not capability.

The benchmark needs a configured provider for model-driven tasks. Deterministic
tasks (readiness, architecture trade-off) can run without generating model
tokens where the task is marked `requires_provider=False`.

## 4. Repository audit

```bash
python3 -m reverseai audit
python3 -m reverseai audit --json
```

It checks version consistency, zero required dependencies, required assets, tool
narration and UI labels, README document links, `.env` hygiene, obvious secret
patterns, UI script policy, and the presence of the test suite.

## 5. Expected skips

Skips are environmental, not hidden failures:

- no-sandbox refusal path — an isolating sandbox exists, so the refusal cannot be
  exercised in-process;
- LIEF absence — LIEF is installed;
- missing-provider-key paths — an API key is present;
- foreign-platform/emulation paths — no configured rootfs or VM.

## 6. Baseline (2026-10-25)

- Version: 0.9.0
- Unit/contract tests: 571 passing, 4 environment-dependent skips
- Tools: every registered tool covered by the contract suite
- Sandbox: bubblewrap + x86_64 seccomp; network/filesystem/env/timeout boundaries
  tested
- Benchmark: development + held-out tasks, with false-verification and refusal
  metrics
- Mutation: strong corpus vs. weak corpus tests included
- Audit: `python3 -m reverseai audit` passes

This baseline is a snapshot, not a permanent claim. Re-run the commands after
changing the code.
