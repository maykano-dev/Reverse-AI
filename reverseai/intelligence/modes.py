"""User-facing interaction modes.

The product has five modes. They change the *contract* with the user, not the
safety rules:

  Ask          investigate and explain, with evidence
  Build        create a new system from requirements
  Modify       change an existing system
  Optimize     improve a measured property while preserving behavior
  Autonomous   pursue an objective within constraints, budget, and approval gates

The older Direct/Reconstruction/Modernisation values remain valid strategy
modes; these product modes are additive.
"""

from __future__ import annotations

MODES = ("ask", "build", "modify", "optimize", "autonomous")

PROMPTS = {
    "ask": (
        "Mode: Ask. Investigate and explain. Do not modify anything. Separate "
        "observed facts from hypotheses, and say what evidence would change "
        "the answer."),
    "build": (
        "Mode: Build. Turn the request into requirements and acceptance "
        "criteria before writing code. Prefer small verified slices. Never "
        "claim the software exists before it is built and tested."),
    "modify": (
        "Mode: Modify. Change an existing system on a copy. Capture a corpus, "
        "state the intended behavioral delta, preserve the rest, and verify "
        "before delivery."),
    "optimize": (
        "Mode: Optimize. Establish a baseline measurement, state the preserved "
        "behavior, change one thing at a time, and report measured results. "
        "Do not call a plausible optimization an improvement."),
    "autonomous": (
        "Mode: Autonomous mission. Work toward the objective within explicit "
        "constraints, budget, deadline, and approval gates. If the objective is "
        "broad, build a world model and run discovery first; propose what is "
        "worth investigating instead of waiting for a narrower question. Stop "
        "at the approval gates. Report progress and unknowns; do not make "
        "irreversible decisions."),
}


def normalize_mode(mode: str | None) -> str:
    value = (mode or "").strip().lower()
    return value if value in MODES else ""


def mode_prompt(mode: str | None) -> str:
    return PROMPTS.get(normalize_mode(mode), "")


def mode_for_strategy(strategy: str) -> str:
    if strategy in ("resource_edit", "byte_patch", "component_replace"):
        return "modify"
    if strategy == "rebuild":
        return "build"
    if strategy == "reimplement":
        return "build"
    return "ask"
