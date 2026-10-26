"""Interactive surfaces rendered inside the chat.

A surface is a validated, task-native UI description. The model proposes it; the
server validates and stores it; the browser renders allowlisted components; the
user's interaction comes back as a structured event. Arbitrary HTML is only
rendered in an opaque-origin sandboxed iframe with no network.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ID_RE = re.compile(r"^sf_[A-Za-z0-9]{6,40}$")
ACTION_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
BLOCK_KINDS = {"text", "markdown", "choice", "form", "table", "chart",
               "graph", "diff", "code", "progress", "approval", "file_drop",
               "custom"}
SURFACE_KINDS = {"question", "form", "dashboard", "review", "approval",
                 "progress", "custom", "workspace"}
FIELD_TYPES = {"text", "textarea", "number", "select", "checkbox", "file"}
MAX_BLOCKS = 24
MAX_STRING = 12000
MAX_HTML = 32000


class SurfaceError(Exception):
    pass


def _clip(value: Any, limit: int = MAX_STRING) -> str:
    return str(value if value is not None else "")[:limit]


def _list(value: Any, limit: int) -> list[Any]:
    return list(value or [])[:limit] if isinstance(value, (list, tuple)) else []


def _choice_options(block: dict[str, Any]) -> list[dict[str, Any]]:
    opts = []
    for raw in _list(block.get("options"), 24):
        if isinstance(raw, str):
            raw = {"value": raw, "label": raw}
        if not isinstance(raw, dict):
            continue
        value = _clip(raw.get("value"), 200)
        if not value:
            continue
        opts.append({
            "value": value,
            "label": _clip(raw.get("label") or value, 200),
            "description": _clip(raw.get("description"), 800),
            "recommended": bool(raw.get("recommended")),
            "risk": _clip(raw.get("risk") or "low", 20),
        })
    if not opts:
        raise SurfaceError("choice block needs at least one option")
    return opts


def _form_fields(block: dict[str, Any]) -> list[dict[str, Any]]:
    fields = []
    for raw in _list(block.get("fields"), 24):
        if not isinstance(raw, dict):
            continue
        name = _clip(raw.get("name"), 80)
        if not name:
            continue
        typ = str(raw.get("type") or "text").lower()
        if typ not in FIELD_TYPES:
            typ = "text"
        field = {
            "name": name,
            "label": _clip(raw.get("label") or name, 200),
            "type": typ,
            "placeholder": _clip(raw.get("placeholder"), 300),
            "required": bool(raw.get("required")),
        }
        if typ == "select":
            field["options"] = [
                _clip(x, 200) for x in _list(raw.get("options"), 30)
                if str(x).strip()
            ]
        fields.append(field)
    if not fields:
        raise SurfaceError("form block needs at least one field")
    return fields


def validate_block(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SurfaceError("each block must be an object")
    kind = str(raw.get("kind") or raw.get("type") or "").lower()
    if kind not in BLOCK_KINDS:
        raise SurfaceError(f"unsupported block kind: {kind or '(missing)'}")
    out: dict[str, Any] = {"kind": kind}
    if kind in ("text", "markdown"):
        out["text"] = _clip(raw.get("text"))
    elif kind == "choice":
        out.update({
            "id": _clip(raw.get("id") or "choice", 80),
            "label": _clip(raw.get("label") or "Choose one", 300),
            "options": _choice_options(raw),
            "multiple": bool(raw.get("multiple")),
            "allow_other": bool(raw.get("allow_other", True)),
            "other_label": _clip(raw.get("other_label") or "Other — type your own", 200),
        })
    elif kind == "form":
        out.update({
            "id": _clip(raw.get("id") or "form", 80),
            "label": _clip(raw.get("label") or "Input", 300),
            "fields": _form_fields(raw),
            "allow_other": bool(raw.get("allow_other", True)),
        })
    elif kind == "table":
        columns = [_clip(c, 120) for c in _list(raw.get("columns"), 30)]
        if not columns:
            raise SurfaceError("table needs columns")
        rows = []
        for row in _list(raw.get("rows"), 200):
            if isinstance(row, dict):
                rows.append([_clip(row.get(c), 1000) for c in columns])
            elif isinstance(row, (list, tuple)):
                rows.append([_clip(v, 1000) for v in row[:len(columns)]])
        out.update({"columns": columns, "rows": rows,
                    "caption": _clip(raw.get("caption"), 500)})
    elif kind == "chart":
        typ = str(raw.get("chart_type") or raw.get("type") or "bar").lower()
        if typ not in ("bar", "line", "pie"):
            typ = "bar"
        labels = [_clip(x, 120) for x in _list(raw.get("labels"), 40)]
        series = []
        for s in _list(raw.get("series"), 8):
            if not isinstance(s, dict):
                continue
            series.append({
                "name": _clip(s.get("name") or "value", 100),
                "values": [float(v) for v in _list(s.get("values"), 40)
                           if isinstance(v, (int, float))],
            })
        if not labels or not series:
            raise SurfaceError("chart needs labels and at least one series")
        out.update({"chart_type": typ, "labels": labels, "series": series,
                    "unit": _clip(raw.get("unit"), 40)})
    elif kind == "graph":
        nodes = []
        for n in _list(raw.get("nodes"), 120):
            if not isinstance(n, dict):
                continue
            nid = _clip(n.get("id"), 100)
            if nid:
                nodes.append({"id": nid, "label": _clip(n.get("label") or nid, 120),
                              "group": _clip(n.get("group"), 60)})
        edges = []
        for e in _list(raw.get("edges"), 300):
            if not isinstance(e, dict):
                continue
            src, dst = _clip(e.get("from"), 100), _clip(e.get("to"), 100)
            if src and dst:
                edges.append({"from": src, "to": dst,
                              "label": _clip(e.get("label"), 80)})
        if not nodes:
            raise SurfaceError("graph needs nodes")
        out.update({"nodes": nodes, "edges": edges,
                    "caption": _clip(raw.get("caption"), 500)})
    elif kind == "diff":
        out.update({"before": _clip(raw.get("before"), 20000),
                    "after": _clip(raw.get("after"), 20000),
                    "filename": _clip(raw.get("filename") or "change", 200)})
    elif kind == "code":
        out.update({"language": _clip(raw.get("language") or "text", 40),
                    "text": _clip(raw.get("text"), 20000)})
    elif kind == "progress":
        out.update({"value": max(0, min(100, float(raw.get("value", 0) or 0))),
                    "max": max(1, float(raw.get("max", 100) or 100)),
                    "label": _clip(raw.get("label"), 300),
                    "status": _clip(raw.get("status") or "running", 40)})
    elif kind == "approval":
        out.update({
            "action": _clip(raw.get("action"), 100),
            "target": _clip(raw.get("target"), 500),
            "risk": _clip(raw.get("risk") or "high", 30),
            "reversible": bool(raw.get("reversible", False)),
            "amount": raw.get("amount"),
            "currency": _clip(raw.get("currency") or "USD", 10),
            "rollback": _clip(raw.get("rollback"), 1000),
            "detail": _clip(raw.get("detail"), 2000),
        })
        if not out["action"] or not out["target"]:
            raise SurfaceError("approval needs action and target")
    elif kind == "file_drop":
        out.update({"accept": _clip(raw.get("accept") or "*/*", 200),
                    "multiple": bool(raw.get("multiple")),
                    "label": _clip(raw.get("label") or "Drop files here", 300)})
    elif kind == "custom":
        html = _clip(raw.get("html"), MAX_HTML)
        if not html:
            raise SurfaceError("custom block needs html")
        out.update({"html": html, "height": max(120, min(1200,
                    int(raw.get("height", 360) or 360)))})
    return out


def validate_surface(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise SurfaceError("surface must be an object")
    surface_id = str(spec.get("id") or "")
    if not surface_id:
        surface_id = "sf_" + uuid.uuid4().hex[:12]
    if not ID_RE.match(surface_id):
        raise SurfaceError("invalid surface id")
    kind = str(spec.get("kind") or "question").lower()
    if kind not in SURFACE_KINDS:
        kind = "question"
    blocks = [validate_block(b) for b in _list(spec.get("blocks"), MAX_BLOCKS)]
    if not blocks:
        raise SurfaceError("surface needs at least one block")
    actions = []
    for raw in _list(spec.get("actions"), 8):
        if isinstance(raw, str):
            raw = {"id": raw, "label": raw}
        if not isinstance(raw, dict):
            continue
        aid = str(raw.get("id") or "")
        if not ACTION_RE.match(aid):
            continue
        actions.append({
            "id": aid,
            "label": _clip(raw.get("label") or aid.replace("_", " ").title(), 120),
            "kind": _clip(raw.get("kind") or "submit", 30),
            "risk": _clip(raw.get("risk") or "low", 30),
        })
    if not actions:
        actions = [{"id": "submit", "label": "Continue",
                    "kind": "submit", "risk": "low"}]
    return {
        "id": surface_id,
        "kind": kind,
        "title": _clip(spec.get("title") or "Decision", 300),
        "description": _clip(spec.get("description"), 4000),
        "blocks": blocks,
        "actions": actions,
        "allow_other": bool(spec.get("allow_other", True)),
        "persist": bool(spec.get("persist", True)),
        "created_at": float(spec.get("created_at") or time.time()),
        "meta": dict(spec.get("meta") or {}),
    }


@dataclass
class SurfaceEvent:
    id: str
    surface_id: str
    job_id: str
    action_id: str
    value: dict[str, Any] = field(default_factory=dict)
    other_text: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SurfaceEventStore:
    def __init__(self, directory: str | os.PathLike) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str, surface_id: str) -> Path:
        if not job_id.startswith("job_") or not ID_RE.match(surface_id):
            raise SurfaceError("invalid surface event path")
        return self.dir / f"{job_id}__{surface_id}.jsonl"

    def append(self, job_id: str, surface_id: str, event: SurfaceEvent) -> Path:
        path = self._path(job_id, surface_id)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event.to_dict()) + "\n")
        return path

    def list(self, job_id: str, surface_id: str) -> list[dict[str, Any]]:
        path = self._path(job_id, surface_id)
        out = []
        try:
            for line in path.read_text("utf-8").splitlines():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass
        return out


def event_from_body(job_id: str, surface: dict[str, Any],
                    body: dict[str, Any]) -> SurfaceEvent:
    action_id = str(body.get("action_id") or "submit")
    allowed = {a["id"] for a in surface.get("actions") or []}
    if action_id not in allowed:
        raise SurfaceError(f"unknown action: {action_id}")
    value = body.get("value")
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise SurfaceError("value must be an object")
    return SurfaceEvent(
        "ev_" + uuid.uuid4().hex[:12], surface["id"], job_id, action_id,
        {str(k): v for k, v in list(value.items())[:50]},
        _clip(body.get("other_text"), 4000))


def find_surface(surfaces: list[dict[str, Any]], surface_id: str) -> dict[str, Any] | None:
    for s in surfaces or []:
        if s.get("id") == surface_id:
            return s
    return None
