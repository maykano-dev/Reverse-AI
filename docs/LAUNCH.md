# Launch kit

Copy-paste material for a real launch. Adjust the voice, but keep the claims
honest: ReverseAI is a beta, it refuses execution when the host cannot isolate
it, and some agent features (workstations, Telegram, vault) are deliberately not
implemented yet.

## One-liner

> ReverseAI: an autonomous agent that understands, modifies, rebuilds, and
> verifies software. Real bytes, a hardened sandbox, and a behavioral test
> before any modified file is delivered.

## Short description (160 chars)

> Open-source agent for reverse engineering: analyze a binary or site, make the
> change in a hardened sandbox, verify it, and get the artifact plus evidence.

## Show HN

**Title:** Show HN: ReverseAI, an agent that modifies software and proves it works

**Body:**

I built ReverseAI because most "AI for reverse engineering" tools stop at a
description. They tell you what a binary probably does. They do not change it,
test the change, or show you why they believe it worked.

ReverseAI closes that loop. Drop in a PE/ELF/Mach-O binary, an APK, an archive,
or a URL. Say what you want in plain language. The agent plans, reads the real
bytes, uses tools through a permission-mediated interface, patches a copy, runs a
behavioral comparison in a bubblewrap sandbox, and delivers the artifact with
believed/observed/verified evidence.

A few things I care about:

- **It refuses to fake containment.** If the host cannot isolate untrusted code,
  execution is refused, not silently run on your machine.
- **The reasoning is visible.** You get a plan, a natural timeline, tool cards
  with real output, sources, and evidence tiers. No raw tool names.
- **It is honest about scope.** It does not modify any binary. It supports a
  growing set of targets and says what it cannot do.

It is MIT, Python 3.11+, and the core has zero third-party dependencies. There is
an optional mobile-first PWA, durable memory, web research with citations,
routines, and specialist templates.

The landing page is here: https://maykano-dev.github.io/Reverse-AI/
Source: https://github.com/maykano-dev/Reverse-AI

I would especially value feedback on the sandbox boundary, the evidence model,
and whether the "verify the change" loop is useful in your actual workflow.

## Product Hunt

**Tagline:** An agent that takes software apart, then puts it back together.

**Description:**

ReverseAI is an open-source engineering agent for compiled software and the web.
It analyzes binaries and sites, makes the change you ask for in plain language,
tests it in a hardened sandbox, and hands back a working artifact plus the
evidence that it works.

Unlike a chatbot with a disassembler prompt, ReverseAI has a real tool layer, a
permission mediator, evidence tiers, and a sandbox that refuses to run untrusted
code on the host when isolation is unavailable. It can also research with
sources, remember preferences, run scheduled routines, and delegate to specialist
agents.

Free and MIT. Bring your own model key.

## A short thread

1. Most AI reverse-engineering tools stop at "here is what the binary probably does." That is a demo, not an engineer.
2. ReverseAI closes the loop: analyze the real bytes, change a copy, test it in a sandbox, prove the behavior changed, and only then deliver the file. If the test fails, the file is withheld and the reason is shown.
3. The important word is *prove*. Findings are tiered believed, observed, verified. A successful build is not a working modification, and an unverified binary is withheld.
4. The sandbox is not decoration: bubblewrap, no network, read-only system, dropped capabilities, RLIMITs. If the host cannot isolate it, the agent refuses.
5. The thinking is visible: a plan, a natural timeline, tool cards, sources, and evidence. No raw tool names, no "investigating" filler.
6. It also remembers, researches with citations, runs routines, and delegates to specialists. One engine, not six forks.
7. Open source, MIT, zero-dependency core: https://github.com/maykano-dev/Reverse-AI
8. Landing page and screenshots: https://maykano-dev.github.io/Reverse-AI/

## Reddit / lobste.rs

**Title:** ReverseAI: an open-source agent that modifies binaries and verifies the change

Most AI RE tools are description engines. I wanted one that actually changes the
artifact and proves the change. ReverseAI reads PE/ELF/Mach-O, patches a copy,
runs original vs modified in a bubblewrap sandbox, and reports believed vs
observed vs verified evidence. The core is stdlib-only and MIT. It refuses
untrusted execution when the host cannot contain it. Feedback on the sandbox and
evidence model welcome.

## What not to claim

- Do not say "modifies any binary."
- Do not say "fully isolated" while seccomp/cgroups are still on the roadmap.
- Do not claim the deferred personal-agent features (live desktop, Telegram,
  vault, persistent squads) are shipped.
- Do not promise a hosted demo that does not exist; link the landing page and the
  one-click deploy instead.
