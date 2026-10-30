"""Capability evaluation harness.

A fast, model-free set of checks that exercise real capabilities end to end
(document generation, rendering, studio round-trips, verification, analysis).
Run it on every change and model swap to catch regressions before users do:

    python3 -m reverseai eval
    python3 -m reverseai eval --category docgen --json

This complements the unit tests: the cases here are outcome-level ("a generated
deck is a valid, themed PowerPoint and renders to an image"), which is what a
user actually feels. Model-dependent agent evals can be added later behind an
API key; these stay deterministic so they're free to run constantly.
"""

from .harness import Case, Result, run_cases, summarize

__all__ = ["Case", "Result", "run_cases", "summarize"]
