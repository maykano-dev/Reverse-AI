# ReverseAI

**Understand. Modify. Rebuild.**

An autonomous reverse-engineering engineer. Hand it a compiled program and a
goal in plain language; it investigates how the program works, makes the change,
tests it in isolation, and returns a working artifact with evidence.

This is the early foundation. Today it does static binary analysis; the agent,
modification engine, and sandbox are being built on top of it. See
[CLAUDE.md](CLAUDE.md) for the full spec, architecture, and roadmap.

## Quick start

No dependencies required — Python 3.11+ and standard binutils only.

```bash
# Analyze any PE / ELF / Mach-O binary
python3 -m reverseai analyze /usr/bin/objdump

# Machine-readable output
python3 -m reverseai analyze /path/to/app.exe --json

# Run the tests
python3 -m unittest discover -s tests -v
```

## What it reports today

- Container format (PE / ELF / Mach-O), architecture, bitness, endianness
- Hashes (MD5/SHA1/SHA256) and entropy (whole-file + per section)
- Entry point, subsystem, exe-vs-dll / ELF type
- Sections with addresses, sizes, permissions, and entropy
- Imported libraries and symbols (PE)
- Extracted strings (ASCII + UTF-16LE)

## Status

`v0.0.1` — static analysis engine. Not yet: the AI agent loop, binary
modification, sandboxed execution, or the web UI. Those are the next milestones.
