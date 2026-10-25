"""Signed verification reports.

A report is a durable, human-readable statement of what was attempted and what
was actually demonstrated. It is assembled from the Job record and the
verification result, then signed over a canonical JSON representation.

Signing:
  * If ``REVERSEAI_REPORT_KEY`` is set, use HMAC-SHA256 with that key.
  * Otherwise use a plain SHA-256 digest.

The digest covers every report field except ``signature`` itself, so changing the
goal, a test result, the artifact hash, or the timestamp invalidates it. The HTML
renderer is self-contained: inline CSS, no scripts, no external resources.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import time
from typing import Any

REPORT_VERSION = 1
_KEY_ENV = "REVERSEAI_REPORT_KEY"


class ReportError(Exception):
    pass


def _key() -> str:
    return os.environ.get(_KEY_ENV, "").strip()


def _canonical(report: dict[str, Any]) -> bytes:
    body = {k: v for k, v in report.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str).encode("utf-8")


def sign_report(report: dict[str, Any]) -> str:
    key = _key()
    body = _canonical(report)
    if key:
        return hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hashlib.sha256(body).hexdigest()


def algorithm() -> str:
    return "HMAC-SHA256" if _key() else "SHA256"


def verify_signature(report: dict[str, Any]) -> bool:
    sig = report.get("signature")
    if not isinstance(sig, str) or not sig:
        return False
    if report.get("algorithm") not in (None, algorithm()):
        return False
    expected = sign_report(report)
    return hmac.compare_digest(sig, expected)


def _iso(ts: float | None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts or 0)))


def _environment(verification: dict[str, Any]) -> dict[str, Any]:
    """The isolation that was actually applied, taken from the test snapshots."""
    for attempt in reversed(verification.get("attempts") or []):
        for case in (attempt.get("report") or {}).get("cases") or []:
            for side in ("modified", "original"):
                iso = (case.get(side) or {}).get("isolation")
                if isinstance(iso, dict) and iso.get("backend"):
                    return {"isolation": iso, "source": "sandbox"}
    return {}


def _compact_attempts(verification: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for a in verification.get("attempts") or []:
        report = a.get("report") or {}
        cases = []
        for c in report.get("cases") or []:
            cases.append({
                "name": c.get("name"),
                "args": c.get("args") or [],
                "matched": c.get("matched"),
                "differences": c.get("differences") or [],
                "expected_met": c.get("expected_met"),
                "unexpected": c.get("unexpected"),
            })
        rows.append({
            "attempt": a.get("attempt"),
            "passed": bool(a.get("passed")),
            "reason": a.get("reason", ""),
            "summary": report.get("summary", ""),
            "cases": cases,
        })
    return rows


def build_report(record: dict[str, Any]) -> dict[str, Any]:
    """Assemble a report from a serialized Job plus its verification result."""
    verification = record.get("verification") or {}
    delivery = record.get("delivery") or {}
    evidence = record.get("evidence") or []
    counts = {"believed": 0, "observed": 0, "verified": 0}
    for item in evidence:
        tier = str(item.get("confidence", "")).lower()
        if tier in counts:
            counts[tier] += 1

    artifact_meta = record.get("artifact_meta") or {}
    artifact = {
        "name": artifact_meta.get("name") or record.get("artifact") or "",
        "size": artifact_meta.get("size"),
        "sha256": artifact_meta.get("sha256", ""),
    }
    plan = record.get("modification_plan") or {}
    from .replay import replay_recipe

    attempts = _compact_attempts(verification)
    diff_summary = (verification.get("test_summary")
                    or record.get("differential") or {})
    if not diff_summary and attempts:
        diff_summary = {"summary": attempts[-1].get("summary", "")}
    verified = bool(verification.get("verified")) and int(
        verification.get("passed_tests", 0) or 0) >= 1
    if verified:
        tier = "verified"
    elif counts["observed"] or attempts:
        tier = "observed"
    elif counts["believed"]:
        tier = "believed"
    else:
        tier = "unverified"

    report: dict[str, Any] = {
        "version": REPORT_VERSION,
        "generated_at": _iso(record.get("finished_at") or record.get("created_at")),
        "job_id": record.get("id", ""),
        "goal": record.get("goal", ""),
        "target": record.get("target_path", ""),
        "status": record.get("status", ""),
        "change_summary": (verification.get("reason") or
                           delivery.get("reason") or
                           record.get("final_answer", "")),
        "evidence_tier": tier,
        "evidence_counts": counts,
        "evidence": [
            {
                "claim": e.get("claim", ""),
                "confidence": e.get("confidence", ""),
                "source": e.get("source", ""),
                "detail": e.get("detail", ""),
            }
            for e in evidence
        ],
        "tests": attempts,
        "tests_run": len(attempts),
        "tests_passed": int(verification.get("passed_tests", 0) or 0),
        "differential": {
            "summary": diff_summary.get("summary", ""),
            "matched": diff_summary.get("matched") or [],
            "differed": diff_summary.get("differed") or [],
            "unexpected": diff_summary.get("unexpected") or [],
            "expected_delta_met": diff_summary.get("expected_delta_met"),
        },
        "artifact": artifact,
        "delivery": {
            "allowed": bool(delivery.get("allowed")),
            "reason": delivery.get("reason", ""),
        },
        "mode": record.get("mode", ""),
        "strategy": plan.get("strategy", ""),
        "world_model": record.get("world_model") or {},
        "opportunities": record.get("opportunities") or [],
        "test_strength": record.get("test_strength") or {},
        "plan": {
            "steps": [
                {"id": s.get("id"), "title": s.get("title"),
                 "status": s.get("status")}
                for s in plan.get("steps") or []
            ],
            "blast_radius": plan.get("blast_radius") or {},
        },
        "environment": _environment(verification),
        "replay": replay_recipe(record),
        "sources": record.get("sources") or [],
        "algorithm": algorithm(),
    }
    report["signature"] = sign_report(report)
    return report


def build_from_job(record: dict[str, Any]) -> dict[str, Any]:
    return build_report(record)


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def render_html(report: dict[str, Any]) -> str:
    """Self-contained HTML. No scripts, stylesheets, images, or network calls."""
    counts = report.get("evidence_counts") or {}
    artifact = report.get("artifact") or {}
    tests = report.get("tests") or []
    diff = report.get("differential") or {}
    test_rows = []
    for t in tests:
        cases = t.get("cases") or []
        case_rows = "".join(
            f"<tr><td>{_e(c.get('name'))}</td>"
            f"<td>{'matched' if c.get('matched') else 'differed'}</td>"
            f"<td>{_e(', '.join(c.get('differences') or []) or 'none')}</td>"
            f"<td>{_e(c.get('expected_met'))}</td></tr>"
            for c in cases
        )
        test_rows.append(
            f"<section class='attempt'><h3>Attempt {_e(t.get('attempt'))}: "
            f"{'passed' if t.get('passed') else 'failed'}</h3>"
            f"<p>{_e(t.get('reason'))}</p><p class='muted'>{_e(t.get('summary'))}</p>"
            + (f"<table><thead><tr><th>Input</th><th>Behavior</th>"
               f"<th>Differences</th><th>Expected</th></tr></thead>"
               f"<tbody>{case_rows}</tbody></table>" if case_rows else "")
            + "</section>")
    evidence_rows = "".join(
        f"<tr><td><span class='tier {_e(e.get('confidence'))}'>"
        f"{_e(e.get('confidence'))}</span></td><td>{_e(e.get('claim'))}</td>"
        f"<td>{_e(e.get('source'))}</td></tr>"
        for e in report.get("evidence") or []
    )
    delivery = report.get("delivery") or {}
    environment = (report.get("environment") or {}).get("isolation") or {}
    blocked = not delivery.get("allowed")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="reverseai-signature" content="{_e(report.get('signature'))}">
<title>ReverseAI verification report</title>
<style>
:root{{--bg:#fbfbfd;--card:#fff;--text:#1d1d1f;--dim:#6e6e73;--line:#e5e5ea;
--accent:#0a84ff;--verified:#168a43;--observed:#0a84ff;--believed:#c47f00;--bad:#c00}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111;--card:#1b1b1e;--text:#f5f5f7;
--dim:#a1a1a8;--line:#333;--accent:#4aa3ff;--verified:#35d16a;--observed:#4aa3ff;
--believed:#ffb340;--bad:#ff6961}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}}
main{{max-width:880px;margin:0 auto;padding:32px 20px 60px}}
h1{{font-size:26px;letter-spacing:-.03em;margin:0 0 6px}}h2{{font-size:17px;
margin:26px 0 8px}}h3{{font-size:14px;margin:18px 0 6px}}.muted{{color:var(--dim)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;
padding:16px 18px;margin:12px 0}}
.badge{{display:inline-block;border-radius:999px;padding:4px 10px;font-size:11px;
font-weight:700;text-transform:uppercase;letter-spacing:.05em;background:#eee;
color:var(--dim)}}.badge.verified{{background:#e6f6ec;color:var(--verified)}}
.badge.blocked{{background:#fdecec;color:var(--bad)}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;margin:8px 0}}
th,td{{border-bottom:1px solid var(--line);text-align:left;padding:7px 6px;
vertical-align:top}}th{{color:var(--dim);font-weight:600}}
.tier{{font-size:10px;font-weight:700;text-transform:uppercase;padding:2px 6px;
border-radius:5px;background:#eee}}.tier.verified{{color:var(--verified)}}
.tier.observed{{color:var(--observed)}}.tier.believed{{color:var(--believed)}}
code,pre{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px}}
pre{{white-space:pre-wrap;word-break:break-word;background:var(--bg);
border:1px solid var(--line);border-radius:10px;padding:12px}}
.kv{{display:grid;grid-template-columns:170px 1fr;gap:4px 12px;font-size:13px}}
.kv b{{color:var(--dim);font-weight:600}}footer{{margin-top:30px;color:var(--dim);
font-size:11px;border-top:1px solid var(--line);padding-top:12px}}
@media(max-width:600px){{.kv{{grid-template-columns:1fr}}}}
</style></head><body><main>
<h1>Verification report</h1>
<p class="muted">ReverseAI · {_e(report.get('generated_at'))}</p>
<div class="card"><span class="badge {_e(report.get('evidence_tier'))}">{_e(report.get('evidence_tier'))}</span>
{(' <span class="badge blocked">delivery blocked</span>' if blocked else '')}
<div class="kv" style="margin-top:12px">
<b>Job</b><span>{_e(report.get('job_id'))}</span>
<b>Goal</b><span>{_e(report.get('goal'))}</span>
<b>Target</b><span>{_e(report.get('target'))}</span>
<b>Status</b><span>{_e(report.get('status'))}</span>
<b>Change</b><span>{_e(report.get('change_summary'))}</span>
<b>Delivery</b><span>{'allowed' if not blocked else 'blocked'}: {_e(delivery.get('reason'))}</span>
<b>Mode</b><span>{_e(report.get('mode') or '(not set)')}</span>
<b>Strategy</b><span>{_e(report.get('strategy') or '(not set)')}</span>
<b>World model</b><span>{_e(report.get('world_model', {}).get('nodes', 'not recorded'))} nodes · {_e(report.get('world_model', {}).get('unresolved', 0))} unresolved</span>
<b>Test strength</b><span>{_e((report.get('test_strength') or {}).get('mutation_score', 'not measured'))}{' mutation score' if (report.get('test_strength') or {}).get('mutation_score') is not None else ''}</span>
</div></div>
<h2>Environment</h2>
<div class="card"><div class="kv">
<b>Sandbox</b><span>{_e(environment.get('backend') or '(not recorded)')}</span>
<b>Isolation</b><span>{_e(environment.get('level'))} · network blocked {_e(environment.get('network_blocked'))} · filesystem {_e(environment.get('filesystem'))}</span>
<b>Capabilities dropped</b><span>{_e(environment.get('capabilities_dropped'))}</span>
<b>seccomp</b><span>{_e(environment.get('seccomp'))}</span>
<b>Landlock</b><span>{_e(environment.get('landlock', False))}</span>
<b>cgroup v2</b><span>{_e(environment.get('cgroup', False))}</span>
</div></div>
<h2>Evidence</h2>
<div class="card"><table><thead><tr><th>Tier</th><th>Claim</th><th>Source</th></tr></thead>
<tbody>{evidence_rows or '<tr><td colspan="3" class="muted">No evidence recorded.</td></tr>'}</tbody></table>
<p class="muted">believed {_e(counts.get('believed', 0))} · observed {_e(counts.get('observed', 0))} · verified {_e(counts.get('verified', 0))}</p></div>
<h2>Tests</h2>
<div class="card">{(''.join(test_rows) if test_rows else '<p class="muted">No behavioral test was run.</p>')}</div>
<h2>Differential testing</h2>
<div class="card"><p>{_e(diff.get('summary') or 'No differential test summary.')}</p>
<p class="muted">matched: {_e(', '.join(diff.get('matched') or []) or 'none')} ·
differed: {_e(', '.join(diff.get('differed') or []) or 'none')} ·
unexpected: {_e(', '.join(diff.get('unexpected') or []) or 'none')}</p></div>
<h2>Artifact</h2>
<div class="card"><div class="kv">
<b>Name</b><span>{_e(artifact.get('name') or '(none)')}</span>
<b>Size</b><span>{_e(artifact.get('size'))}</span>
<b>SHA-256</b><span><code>{_e(artifact.get('sha256') or '(none)')}</code></span>
</div></div>
<h2>Replay</h2>
<div class="card"><p>Re-run this verification without a model:</p>
<pre>{_e((report.get('replay') or {}).get('command') or 'A replay command is not available for this report.')}</pre>
<p class="muted">original sha256: <code>{_e((report.get('replay') or {}).get('original_sha256') or '(not recorded)')}</code><br>
modified sha256: <code>{_e((report.get('replay') or {}).get('modified_sha256') or '(not recorded)')}</code></p></div>
<h2>Signature</h2>
<div class="card"><p class="muted">{_e(report.get('algorithm'))}</p>
<pre>{_e(report.get('signature'))}</pre>
<p class="muted">The signature covers every field above. Any change invalidates it.</p></div>
<footer>Generated locally by ReverseAI. This page makes no network requests.</footer>
</main></body></html>"""
