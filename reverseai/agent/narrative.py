"""Natural-language narration for the reasoning timeline.

The UI should read like a competent person working, not a debug log. This module
turns tool calls into short, specific sentences ("Checking the bytes around
0x400", "Running it in the sandbox") and builds a small plan for the turn.

It deliberately avoids the word "investigating" and other stiff phrasing.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

# Keep these in sync with the icon set in static/app.js.
_TOOL_ICON = {
    "host_capabilities": "cpu",
    "analyze_binary": "search",
    "read_bytes": "code",
    "list_strings": "file",
    "disassemble": "code",
    "list_functions": "bars",
    "analyze_apk": "box",
    "assess_heuristics": "alert",
    "run_in_sandbox": "terminal",
    "record_finding": "check",
    "apply_byte_patch": "code",
    "verify_against_original": "check",
    "verify_modification": "check",
    "differential_test": "bars",
    "choose_modification_strategy": "search",
    "plan_and_modify": "sparkle",
    "diff_modified": "bars",
    "extract_archive": "archive",
    "clone_website": "globe",
    "add_imported_library": "code",
    "add_section": "code",
    "list_dir": "file",
    "read_file": "file",
    "write_file": "file",
    "edit_file": "code",
    "run_command": "terminal",
    "web_search": "search",
    "web_read": "globe",
    "remember": "box",
    "recall": "search",
    "forget": "x",
    "delegate": "sparkle",
    "list_skills": "sparkle",
    "read_skill": "file",
}


def _short(text: Any, limit: int = 80) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _host(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).hostname or url
    except ValueError:
        return url


def describe_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, str]:
    """A human title, detail, and icon for one tool call."""
    a = args or {}
    title = "Working through it"
    detail = ""
    icon = _TOOL_ICON.get(name, "sparkle")

    if name == "host_capabilities":
        title = "Checking what this machine can do"
        detail = "Looking at the available sandbox and analysis backends."
    elif name == "analyze_binary":
        title = "Reading the file's structure"
        detail = "Format, architecture, sections, imports, and metadata."
    elif name == "read_bytes":
        off = a.get("offset", 0)
        try:
            off = hex(int(off))
        except (ValueError, TypeError):
            off = str(off)
        title = f"Looking at the bytes around {off}"
        detail = "A close look at a specific part of the file."
    elif name == "list_strings":
        needle = _short(a.get("contains", ""), 40)
        title = "Picking out readable text"
        detail = f"Filtering for {needle!r}." if needle else "Finding human-readable strings."
    elif name == "disassemble":
        title = "Reading the machine code"
        detail = "Turning bytes back into instructions."
    elif name == "list_functions":
        title = "Mapping the functions"
        detail = "Finding named routines and where they live."
    elif name == "analyze_apk":
        title = "Opening up the app package"
        detail = "Manifest, permissions, DEX files, and native libraries."
    elif name == "assess_heuristics":
        title = "Looking for risk signals"
        detail = "Packing, self-modifying code, and suspicious imports."
    elif name == "run_in_sandbox":
        title = "Running it in the sandbox"
        detail = "Watching what it actually does, with network and host access cut off."
    elif name == "record_finding":
        tier = str(a.get("confidence", "observed")).lower()
        article = "an" if tier[:1] in "aeiou" else "a"
        title = f"Noting {article} {tier} finding"
        detail = _short(a.get("claim", ""), 120)
    elif name in ("apply_byte_patch", "add_section", "add_imported_library"):
        title = "Changing a copy of the file"
        detail = "The original stays untouched."
    elif name == "verify_against_original":
        title = "Comparing both versions"
        detail = "Same inputs, same sandbox, then compare the behavior."
    elif name == "verify_modification":
        title = "Proving the change in the sandbox"
        detail = "Running the declared behavioral test before delivery."
    elif name == "differential_test":
        title = "Testing across a set of inputs"
        detail = "Comparing the original and the change for unexpected regressions."
    elif name == "choose_modification_strategy":
        title = "Choosing the safest way to make the change"
        detail = "Comparing a resource edit, a byte patch, a component swap, a rebuild, and a reimplementation."
    elif name == "plan_and_modify":
        title = "Planning the change end to end"
        detail = "Choosing a strategy, scoping the blast radius, implementing on a copy, and proving it."
    elif name == "diff_modified":
        title = "Checking what changed"
        detail = "Sections, imports, exports, size, and entropy."
    elif name == "extract_archive":
        title = "Unpacking the archive safely"
        detail = "Watching for bombs and path tricks before writing anything."
    elif name == "clone_website":
        title = "Rebuilding the site"
        detail = f"Fetching and packaging {_host(str(a.get('url', '')))}."
    elif name == "list_dir":
        title = "Looking through the project"
        detail = _short(a.get("path", "."), 60)
    elif name == "read_file":
        title = "Reading a file"
        detail = _short(a.get("path", ""), 80)
    elif name == "write_file":
        title = "Writing a file"
        detail = _short(a.get("path", ""), 80)
    elif name == "edit_file":
        title = "Editing a file"
        detail = _short(a.get("path", ""), 80)
    elif name == "run_command":
        argv = a.get("argv") or []
        cmd = " ".join(str(x) for x in argv[:4]) if isinstance(argv, list) else str(argv)
        title = "Running a command"
        detail = _short(cmd, 90)
    elif name == "web_search":
        title = "Searching the web"
        detail = f"Looking for: {_short(a.get('query', ''), 90)}"
    elif name == "web_read":
        title = f"Reading {_host(str(a.get('url', '')))}"
        detail = "Pulling out the useful text and checking the source."
    elif name == "remember":
        title = "Saving a note for later"
        detail = _short(a.get("text", ""), 110)
    elif name == "recall":
        title = "Checking past notes"
        detail = _short(a.get("query", "everything"), 80)
    elif name == "forget":
        title = "Removing a saved note"
    elif name == "delegate":
        title = f"Bringing in the {a.get('specialist', 'specialist')}"
        detail = _short(a.get("task", ""), 110)
    elif name == "list_skills":
        title = "Checking available playbooks"
    elif name == "read_skill":
        title = f"Loading the {a.get('name', 'playbook')} playbook"
    return {"title": title, "detail": detail, "icon": icon, "tool": name}


_PLANS: dict[str, list[tuple[str, str]]] = {
    "reverse": [
        ("Get the lay of the land", "Read the file, not a guess about it."),
        ("Understand how it works", "Follow the code paths and the imports."),
        ("Try it safely", "Run it only inside the sandbox."),
        ("Make the change", "Work on a copy and keep the original untouched."),
        ("Prove it works", "Compare behavior and hand back the file."),
    ],
    "engineer": [
        ("Read the project", "Find the relevant files and how they fit."),
        ("Find the change", "Make the smallest coherent edit."),
        ("Run the tests", "Real output beats assurances."),
        ("Review the diff", "Check nothing important broke."),
    ],
    "researcher": [
        ("Search widely", "Find more than one angle."),
        ("Read the best sources", "Prefer primary material."),
        ("Check the evidence", "Discard claims the sources do not support."),
        ("Answer with citations", "Show exactly where it came from."),
    ],
    "security": [
        ("Look without running", "Static first, always."),
        ("Map the risk", "Packing, persistence, injection, network, crypto."),
        ("Test in the sandbox", "Only if the containment is real."),
        ("Report with confidence", "Separate evidence from suspicion."),
    ],
    "mobile": [
        ("Open the package", "Manifest, permissions, DEX, and ABIs."),
        ("Read the native code", "Treat bundled ELF libraries as targets."),
        ("Check the data", "Strings, endpoints, and embedded assets."),
        ("Deliver findings", "Be clear about what needs external tooling."),
    ],
    "writer": [
        ("Understand the audience", "Who is this for, and what should they do?"),
        ("Draft", "Lead with the point."),
        ("Tighten", "Cut filler, keep the voice."),
    ],
    "data": [
        ("Inspect the shape", "Columns, types, and obvious gaps."),
        ("Analyze", "Keep the steps reproducible."),
        ("Show the numbers", "Every conclusion needs its figure."),
    ],
    "general": [
        ("Understand the ask", "Work out what actually helps."),
        ("Do the work", "Use the right tool for the job."),
        ("Check the result", "Make sure it holds up."),
    ],
}


def plan_for(template: str | None, has_target: bool = False,
             goal: str = "") -> list[dict[str, str]]:
    """A short plan shown as a collapsible Steps block."""
    rows = _PLANS.get((template or "general").lower(), _PLANS["general"])
    if not has_target and template in (None, "", "general", "researcher", "writer"):
        rows = [r for r in rows if r[0] != "Try it safely"]
    return [{"title": t, "detail": d} for t, d in rows]


def thought_label(steps: int) -> str:
    if steps <= 1:
        return "Thought it through"
    return f"Thought through {steps} steps"
