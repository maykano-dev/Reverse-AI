# Security Policy

ReverseAI analyzes and executes software it does not trust. Please read the full
threat model in [`docs/SECURITY.md`](docs/SECURITY.md).

## Reporting a vulnerability

Open a **private security advisory** on this repository. Do not file a public
issue with working exploit details.

Please include:

- the affected version or commit,
- the smallest reproduction you can share,
- what you expected versus what happened,
- whether the issue crosses a trust boundary (host, sandbox, API, model), and
- any suggested fix.

## Supported versions

The `main` branch and the latest release receive security fixes. Older releases
may not.

## Scope

In scope: the API, auth and path guard, sandbox backends, archive handling,
SSRF protections, preview isolation, prompt-injection handling, secret handling,
and the Docker image.

Out of scope: findings in optional third-party tools (Ghidra, Qiling, Tesseract,
Playwright) that are not caused by ReverseAI's integration; and attacks that
require the operator to enable a documented unsafe option.

## Known limitations

See the "Known limitations" section of [`docs/SECURITY.md`](docs/SECURITY.md).
We would rather state a gap than imply protection we do not have.
