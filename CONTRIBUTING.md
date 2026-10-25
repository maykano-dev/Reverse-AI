# Contributing to ReverseAI

Thank you for helping. ReverseAI is a security-sensitive agent, so the bar for a
change is a little higher than "it works on my machine."

## The short version

1. **Open an issue first** for anything larger than a typo or a small fix.
2. **Keep the core dependency-free.** Optional libraries enhance, never gate, the
   stdlib core.
3. **Ship a test with every capability.** A test must demonstrate the behavior,
   not merely that a function returned.
4. **Never run untrusted code on the host.** Use the sandbox.
5. **Be honest in reports.** Separate believed, observed, and verified. Say what
   the change does not protect against.
6. **Do not expose internal tool names in user-facing text.** The UI is written
   for people, not debug logs.

## Setup

```bash
git clone https://github.com/maykano-dev/Reverse-AI.git
cd Reverse-AI
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
python -m unittest discover -s tests -v
```

System tools that unlock the full test suite: `bubblewrap`, `binutils`, `cc`.
Ghidra, Qiling, Tesseract, and Playwright are optional.

## Where a change goes

| Kind of change | Where |
|---|---|
| New binary analysis | `reverseai/core/` + a tool in `agent/builtins.py` |
| New capability | a `Tool` with a permission tier |
| New isolation technology | a `Sandbox` backend registered with the factory |
| New model provider | an `LLMProvider` |
| New UI component | `server/static/` (no build step) |
| New storage | a small store with atomic writes, like `agent/memory.py` |
| New specialist role | `agent/templates.py` |

## Tests and style

```bash
python -m unittest discover -s tests -v
python -m compileall -q reverseai
node --check reverseai/server/static/app.js
ruff check reverseai            # advisory
```

- Prefer clear code over clever code.
- Keep modules small and documented with a short module docstring.
- Add type hints where they clarify a contract.
- Do not add an em dash or en dash to user-facing copy.

## CI

The GitHub Actions workflows are staged in `docs/github-workflows/` because a
push token needs the `workflow` scope to create files under `.github/workflows`.
Copy them into place once that token is available. The test command above is the
same suite CI runs.

## Security

Please do not open a public issue with a working exploit. See
[`docs/SECURITY.md`](docs/SECURITY.md) for the threat model and reporting route.

## License

By contributing, you agree that your contribution is licensed under the MIT
License.
