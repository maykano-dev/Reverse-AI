# Reproducible verification

ReverseAI's delivery gate is only useful if someone else can re-run the proof.
This page shows the model-free path.

## 1. Declare the cases

`cases.json` is a list of input cases, or an object with a `cases` key:

```json
{
  "cases": [
    {
      "name": "new-behavior",
      "args": ["--new"],
      "expect": {"stdout": "NEW", "differs": true}
    },
    {
      "name": "unchanged-default",
      "args": ["--keep"],
      "expect": {"stdout": "STABLE", "same_as_original": true}
    }
  ]
}
```

A case can include `stdin`, small input `files`, `stdout`/`stderr` text,
`exit_code`, `stdout_contains`, `stderr_contains`, and `output_files` hashes or
text. Args, stdin, files, and output names are bounded; unsafe names are refused.

## 2. Run the verification

```bash
python3 -m reverseai verify \
  --original ./app \
  --modified ./app.patched \
  --cases cases.json \
  --report report.json
```

A non-zero exit code means the change did not pass. `--report report.html`
produces the self-contained HTML report instead of JSON. Add `--output-file
result.txt` to compare an output file.

The same check is available in Python:

```python
from reverseai.verify.replay import load_cases, replay_record, write_reports

record = replay_record("./app", "./app.patched", load_cases("cases.json"))
print(record["verification"]["verified"], record["verification"]["reason"])
report = write_reports(record, "report.json")
```

## 3. Check the signature

```bash
python3 -m reverseai report verify report.json
```

Set `REVERSEAI_REPORT_KEY` on the machine that signs and on the machine that
checks. Without a key, the report uses SHA-256, which is tamper-evident but not
keyed: anyone can recompute it.

## 4. Replay from a report

Every report includes a `replay` block:

```json
{
  "original": "/work/app",
  "modified": "/work/app.patched",
  "original_sha256": "...",
  "modified_sha256": "...",
  "case_count": 2,
  "cases": [{"name": "new-behavior", "args": ["--new"]}],
  "command": "python3 -m reverseai verify --original /work/app --modified /work/app.patched --cases cases.json --report report.json"
}
```

Use it as a checklist, not as proof by itself. Read the cases and the expected
outputs, then run it on a host with an isolating sandbox.

## 5. Capture a durable corpus

```bash
python3 -m reverseai corpus capture --target ./app --cases smoke.json
python3 -m reverseai corpus list
python3 -m reverseai corpus show <sha256>
```

The agent can load it with `use_corpus: true` in `verify_modification` or
`plan_and_modify`. A missing corpus is an honest failure, not a silent pass.

## What the result does and does not mean

- A pass proves the declared cases on this host, with the recorded isolation.
- It does not prove every input, every platform, or every execution path.
- A target that cannot run natively is analysis-only unless Qiling/QEMU is
  configured. `reverseai readiness` tells you which case you are in.
- A signature proves the report was not altered. It does not make a weak test
  strong.
