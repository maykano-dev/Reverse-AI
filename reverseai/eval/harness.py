"""The eval runner: a list of named cases, each a callable that asserts."""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Case:
    name: str
    category: str
    run: Callable[[], None]          # raises on failure
    note: str = ""


@dataclass
class Result:
    name: str
    category: str
    ok: bool
    ms: float
    detail: str = ""


def run_cases(cases, category: str | None = None) -> list[Result]:
    out: list[Result] = []
    for c in cases:
        if category and c.category != category:
            continue
        start = time.perf_counter()
        ok, detail = True, ""
        try:
            c.run()
        except AssertionError as exc:
            ok, detail = False, f"assertion: {exc}"
        except Exception as exc:  # noqa: BLE001 - report any failure
            ok, detail = False, f"{type(exc).__name__}: {exc}\n" + \
                traceback.format_exc(limit=2)
        out.append(Result(c.name, c.category, ok,
                          (time.perf_counter() - start) * 1000, detail))
    return out


def summarize(results: list[Result]) -> dict:
    passed = sum(1 for r in results if r.ok)
    by_cat: dict[str, dict] = {}
    for r in results:
        d = by_cat.setdefault(r.category, {"passed": 0, "total": 0})
        d["total"] += 1
        d["passed"] += 1 if r.ok else 0
    return {
        "passed": passed,
        "total": len(results),
        "failed": len(results) - passed,
        "ok": passed == len(results),
        "ms": round(sum(r.ms for r in results), 1),
        "by_category": by_cat,
    }


def render_text(results: list[Result]) -> str:
    s = summarize(results)
    lines = [f"ReverseAI eval: {'PASS' if s['ok'] else 'FAIL'}  "
             f"({s['passed']}/{s['total']} in {s['ms']:.0f} ms)", ""]
    for r in results:
        mark = "ok  " if r.ok else "FAIL"
        lines.append(f"  [{mark}] {r.category}/{r.name}  ({r.ms:.0f} ms)")
        if not r.ok and r.detail:
            first = r.detail.strip().splitlines()[0]
            lines.append(f"         {first}")
    cats = ", ".join(f"{k} {v['passed']}/{v['total']}"
                     for k, v in sorted(s["by_category"].items()))
    lines += ["", "  by category: " + cats]
    return "\n".join(lines)
