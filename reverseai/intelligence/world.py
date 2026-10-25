"""A world model and engineering graph with explicit provenance.

The model is intentionally simple: nodes are components, sections, symbols,
requirements, risks, or questions; edges are relationships. Every claim carries a
provenance record and a confidence class. A fact that has not been observed is
never promoted to one.

The same structure serves software, a service dependency graph, and a domain
adapter (firmware, network, robot). The domain-specific parts are attributes and
adapter nodes, not a separate ontology.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

CONFIDENCE_ORDER = {"unknown": 0, "hypothesis": 1, "observed": 2, "verified": 3}
RECORD_KINDS = {
    "requirement", "hypothesis", "experiment", "modification", "test",
    "evidence", "decision", "risk", "question", "opportunity", "skill",
    "mission", "failure",
}
MEMORY_KINDS = {
    "episodic", "semantic", "procedural", "causal", "project", "temporal",
    "evaluation",
}


class WorldModelError(Exception):
    pass


def _now() -> float:
    return time.time()


@dataclass
class Provenance:
    source: str = "agent"
    confidence: str = "hypothesis"
    detail: str = ""
    at: float = field(default_factory=_now)
    invalidated_by: str = ""

    def __post_init__(self) -> None:
        if self.confidence not in CONFIDENCE_ORDER:
            self.confidence = "unknown"

    @property
    def tier(self) -> int:
        return CONFIDENCE_ORDER[self.confidence]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Node:
    id: str
    kind: str
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "name": self.name,
            "attributes": self.attributes, "provenance": self.provenance.to_dict(),
            "tags": list(self.tags),
        }


@dataclass
class Edge:
    source: str
    target: str
    relation: str
    attributes: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "target": self.target,
            "relation": self.relation, "attributes": self.attributes,
            "provenance": self.provenance.to_dict(),
        }


@dataclass
class EngineeringRecord:
    id: str
    kind: str
    title: str
    detail: str = ""
    status: str = "open"          # open | supported | refuted | verified | stale
    links: list[str] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    provenance: Provenance = field(default_factory=Provenance)
    created_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "title": self.title,
            "detail": self.detail, "status": self.status,
            "links": list(self.links), "evidence": list(self.evidence),
            "provenance": self.provenance.to_dict(),
            "created_at": self.created_at,
        }


class WorldModel:
    def __init__(self, name: str = "system") -> None:
        self.name = name
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.records: dict[str, EngineeringRecord] = {}
        self.updated_at = _now()

    # -- nodes / edges -----------------------------------------------------
    def add_node(self, kind: str, name: str, *,
                 attributes: dict[str, Any] | None = None,
                 confidence: str = "observed", source: str = "agent",
                 detail: str = "", tags: list[str] | None = None,
                 node_id: str | None = None) -> Node:
        if not kind or not name:
            raise WorldModelError("node needs a kind and a name")
        for existing in self.nodes.values():
            if (existing.kind == kind and existing.name == name
                    and not existing.provenance.invalidated_by):
                existing.attributes.update(attributes or {})
                if CONFIDENCE_ORDER.get(confidence, 0) > existing.provenance.tier:
                    existing.provenance = Provenance(source, confidence, detail)
                self.updated_at = _now()
                return existing
        nid = node_id or f"n_{uuid.uuid4().hex[:12]}"
        node = Node(nid, kind, name, dict(attributes or {}),
                    Provenance(source, confidence, detail), list(tags or []))
        self.nodes[nid] = node
        self.updated_at = _now()
        return node

    def add_edge(self, source: str, target: str, relation: str, *,
                 attributes: dict[str, Any] | None = None,
                 confidence: str = "observed", source_name: str = "agent") -> Edge:
        if source not in self.nodes or target not in self.nodes:
            raise WorldModelError("edge endpoints must exist")
        for edge in self.edges:
            if (edge.source == source and edge.target == target
                    and edge.relation == relation):
                edge.attributes.update(attributes or {})
                return edge
        edge = Edge(source, target, relation, dict(attributes or {}),
                    Provenance(source_name, confidence))
        self.edges.append(edge)
        self.updated_at = _now()
        return edge

    def get(self, node_id: str) -> Node | None:
        return self.nodes.get(node_id)

    def find(self, kind: str | None = None, name: str | None = None) -> list[Node]:
        out = []
        for node in self.nodes.values():
            if kind and node.kind != kind:
                continue
            if name and name.lower() not in node.name.lower():
                continue
            out.append(node)
        return out

    def neighbors(self, node_id: str, relation: str | None = None) -> list[Node]:
        ids = set()
        for e in self.edges:
            if relation and e.relation != relation:
                continue
            if e.source == node_id:
                ids.add(e.target)
            if e.target == node_id:
                ids.add(e.source)
        return [self.nodes[i] for i in ids if i in self.nodes]

    def outgoing(self, node_id: str, relation: str | None = None) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id
                and (relation is None or e.relation == relation)]

    def ancestors(self, node_id: str, max_depth: int = 6) -> list[Node]:
        return self._walk(node_id, reverse=True, max_depth=max_depth)

    def descendants(self, node_id: str, max_depth: int = 6) -> list[Node]:
        return self._walk(node_id, reverse=False, max_depth=max_depth)

    def _walk(self, node_id: str, *, reverse: bool, max_depth: int) -> list[Node]:
        seen: set[str] = set()
        queue = [(node_id, 0)]
        out: list[Node] = []
        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for e in self.edges:
                src, dst = (e.target, e.source) if reverse else (e.source, e.target)
                if src != current:
                    continue
                if dst in seen or dst == node_id:
                    continue
                seen.add(dst)
                out.append(self.nodes[dst])
                queue.append((dst, depth + 1))
        return out

    # -- engineering records ----------------------------------------------
    def add_record(self, kind: str, title: str, *, detail: str = "",
                   status: str = "open", links: Iterable[str] | None = None,
                   evidence: list[dict[str, Any]] | None = None,
                   confidence: str = "hypothesis", source: str = "agent",
                   record_id: str | None = None) -> EngineeringRecord:
        if kind not in RECORD_KINDS:
            raise WorldModelError(f"unknown record kind: {kind}")
        rid = record_id or f"r_{uuid.uuid4().hex[:12]}"
        rec = EngineeringRecord(
            rid, kind, title[:500], detail[:8000], status,
            [str(x) for x in (links or []) if str(x) in self.nodes],
            list(evidence or []), Provenance(source, confidence), _now())
        self.records[rid] = rec
        self.updated_at = _now()
        return rec

    def link(self, record_id: str, node_id: str) -> None:
        rec = self.records.get(record_id)
        if rec is None:
            raise WorldModelError("record not found")
        if node_id not in self.nodes:
            raise WorldModelError("node not found")
        if node_id not in rec.links:
            rec.links.append(node_id)

    def set_record_status(self, record_id: str, status: str) -> None:
        rec = self.records.get(record_id)
        if rec is None:
            raise WorldModelError("record not found")
        rec.status = status
        if status in ("supported", "verified"):
            rec.provenance.confidence = "verified" if status == "verified" else "observed"

    def invalidate(self, node_id: str, reason: str) -> bool:
        node = self.nodes.get(node_id)
        if node is None:
            return False
        node.provenance.invalidated_by = reason[:500]
        self.updated_at = _now()
        return True

    # -- queries -----------------------------------------------------------
    def weak_evidence(self) -> list[Node]:
        return [n for n in self.nodes.values()
                if n.provenance.tier <= CONFIDENCE_ORDER["hypothesis"]
                and not n.provenance.invalidated_by]

    def unresolved(self) -> list[dict[str, Any]]:
        out = []
        for n in self.weak_evidence():
            out.append({"type": "node", "id": n.id, "name": n.name,
                        "confidence": n.provenance.confidence})
        for r in self.records.values():
            if r.status == "open" and not r.provenance.invalidated_by:
                out.append({"type": r.kind, "id": r.id, "name": r.title,
                            "confidence": r.provenance.confidence})
        return out

    def unverified_requirements(self) -> list[EngineeringRecord]:
        return [r for r in self.records.values()
                if r.kind == "requirement" and r.status not in ("verified", "stale")]

    def weak_components(self) -> list[Node]:
        return [n for n in self.nodes.values()
                if n.kind in ("component", "function", "service", "module",
                              "section", "dataset", "device")
                and n.provenance.tier < CONFIDENCE_ORDER["verified"]]

    def orphaned_records(self) -> list[EngineeringRecord]:
        return [r for r in self.records.values()
                if r.kind in ("decision", "hypothesis", "test")
                and not r.links and r.status == "open"]

    def stale(self) -> list[dict[str, Any]]:
        return [{"type": "node", **n.to_dict()} for n in self.nodes.values()
                if n.provenance.invalidated_by] + [
            {"type": "record", **r.to_dict()} for r in self.records.values()
            if r.provenance.invalidated_by]

    def next_best_tests(self, limit: int = 5) -> list[dict[str, Any]]:
        """Rank untested requirements by how many open questions they touch."""
        tests = [r for r in self.records.values() if r.kind == "test"]
        out = []
        for req in self.unverified_requirements():
            linked_tests = [t for t in tests
                            if req.id in t.links or any(
                                l in t.links for l in req.links)]
            if any(t.status == "verified" for t in linked_tests):
                continue
            out.append({
                "requirement": req.title,
                "record_id": req.id,
                "why": "no linked test; it is a direct acceptance gap",
                "impact": len(req.links) + 1,
            })
        out.sort(key=lambda x: x["impact"], reverse=True)
        return out[:limit]

    # -- persistence -------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "name": self.name,
            "updated_at": self.updated_at,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
            "records": [r.to_dict() for r in self.records.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorldModel":
        wm = cls(str(data.get("name") or "system"))
        for raw in data.get("nodes") or []:
            p = raw.get("provenance") or {}
            wm.nodes[str(raw["id"])] = Node(
                str(raw["id"]), str(raw.get("kind", "unknown")),
                str(raw.get("name", "")), dict(raw.get("attributes") or {}),
                Provenance(str(p.get("source", "")), str(p.get("confidence", "unknown")),
                           str(p.get("detail", "")), float(p.get("at", 0) or 0),
                           str(p.get("invalidated_by", ""))),
                list(raw.get("tags") or []))
        for raw in data.get("edges") or []:
            p = raw.get("provenance") or {}
            wm.edges.append(Edge(
                str(raw["source"]), str(raw["target"]), str(raw.get("relation", "related")),
                dict(raw.get("attributes") or {}),
                Provenance(str(p.get("source", "")), str(p.get("confidence", "unknown")),
                           str(p.get("detail", "")), float(p.get("at", 0) or 0))))
        for raw in data.get("records") or []:
            p = raw.get("provenance") or {}
            wm.records[str(raw["id"])] = EngineeringRecord(
                str(raw["id"]), str(raw.get("kind", "evidence")),
                str(raw.get("title", "")), str(raw.get("detail", "")),
                str(raw.get("status", "open")), list(raw.get("links") or []),
                list(raw.get("evidence") or []),
                Provenance(str(p.get("source", "")), str(p.get("confidence", "unknown")),
                           str(p.get("detail", "")), float(p.get("at", 0) or 0)),
                float(raw.get("created_at", 0) or 0))
        wm.updated_at = float(data.get("updated_at", 0) or _now())
        return wm

    def save(self, path: str | os.PathLike) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".world-", dir=str(p.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, indent=2)
            os.replace(tmp, p)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return p

    @classmethod
    def load(cls, path: str | os.PathLike) -> "WorldModel":
        p = Path(path)
        try:
            if p.stat().st_size > 16 * 1024 * 1024:
                raise WorldModelError("world model file is too large")
            data = json.loads(p.read_text("utf-8"))
        except WorldModelError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise WorldModelError(f"could not load world model: {exc}") from exc
        return cls.from_dict(data)

    def merge(self, other: "WorldModel") -> "WorldModel":
        for n in other.nodes.values():
            self.add_node(n.kind, n.name, attributes=n.attributes,
                          confidence=n.provenance.confidence,
                          source=n.provenance.source, detail=n.provenance.detail,
                          tags=n.tags, node_id=n.id)
        for e in other.edges:
            if e.source in self.nodes and e.target in self.nodes:
                self.add_edge(e.source, e.target, e.relation,
                              attributes=e.attributes,
                              confidence=e.provenance.confidence,
                              source_name=e.provenance.source)
        for r in other.records.values():
            if r.id not in self.records:
                self.records[r.id] = r
        self.updated_at = _now()
        return self

    def summary(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for n in self.nodes.values():
            kinds[n.kind] = kinds.get(n.kind, 0) + 1
        return {
            "name": self.name,
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "records": len(self.records),
            "node_kinds": kinds,
            "unresolved": len(self.unresolved()),
            "weak_components": len(self.weak_components()),
            "unverified_requirements": len(self.unverified_requirements()),
        }


def world_from_analysis(report, *, max_functions: int = 60,
                        max_strings: int = 20) -> WorldModel:
    """Seed a world model from a real ``AnalysisReport``.

    Everything added here is *observed* from the parser, except the explicit
    questions, which are hypotheses. The model does not pretend to know runtime
    behavior.
    """
    wm = WorldModel(name=Path(getattr(report, "path", "target")).name or "target")
    target = wm.add_node(
        "target", wm.name,
        attributes={
            "format": report.fmt.value, "arch": report.arch.value,
            "bits": report.bits, "size": report.size,
            "sha256": (report.hashes or {}).get("sha256", ""),
            "entry_point": report.entry_point,
        },
        confidence="observed", source="analyze_binary",
        detail="parsed container and metadata")
    for s in report.sections:
        if not s.name:
            continue
        node = wm.add_node(
            "section", s.name,
            attributes={"virtual_address": s.virtual_address,
                        "virtual_size": s.virtual_size,
                        "raw_size": s.raw_size, "raw_offset": s.raw_offset,
                        "entropy": s.entropy, "flags": s.flags},
            confidence="observed", source="analyze_binary")
        wm.add_edge(target.id, node.id, "contains")
    for lib, syms in (report.imports or {}).items():
        libnode = wm.add_node(
            "dependency", lib, attributes={"symbols": list(syms)[:200]},
            confidence="observed", source="analyze_binary")
        wm.add_edge(target.id, libnode.id, "imports")
        for sym in list(syms)[:40]:
            sn = wm.add_node("symbol", f"{lib}!{sym}",
                             attributes={"library": lib}, confidence="observed",
                             source="analyze_binary")
            wm.add_edge(libnode.id, sn.id, "provides")
    for name in (report.exports or [])[:200]:
        n = wm.add_node("export", name, confidence="observed",
                        source="analyze_binary")
        wm.add_edge(target.id, n.id, "exports")
    for f in (report.functions or [])[:max_functions]:
        n = wm.add_node(
            "function", str(f.get("name") or f"sub_{int(f.get('address') or 0):x}"),
            attributes={"address": f.get("address"), "size": f.get("size")},
            confidence="observed", source="analyze_binary")
        wm.add_edge(target.id, n.id, "contains")
    for text in (report.strings_sample or [])[:max_strings]:
        if not str(text).strip():
            continue
        n = wm.add_node("string", str(text)[:120], confidence="observed",
                        source="strings")
        wm.add_edge(target.id, n.id, "contains")
    if getattr(report, "entry_point", None) is not None:
        wm.add_record(
            "question", "Which paths are reachable from the entry point?",
            detail="Static analysis found an entry point but has not traced "
                   "reachability. This is an open hypothesis, not a fact.",
            status="open", confidence="hypothesis", source="world_from_analysis",
            links=[target.id])
    if not report.functions:
        wm.add_record(
            "risk", "Symbols are stripped or unavailable",
            detail="Function-level claims will need runtime or disassembly "
                   "evidence, not names.",
            status="open", confidence="observed", source="world_from_analysis",
            links=[target.id])
    return wm


class MemoryFabric:
    """Multiple memory classes with provenance and a project boundary.

    The classes are intentionally separate: a verified procedure is not the same
    thing as a project decision or a temporal observation. Retrieval never
    crosses a project boundary unless the caller explicitly asks for global
    knowledge.
    """

    def __init__(self, name: str = "project") -> None:
        self.name = name
        self.entries: list[dict[str, Any]] = []

    def store(self, kind: str, text: str, *, scope: str = "project",
              source: str = "agent", confidence: str = "observed",
              meta: dict[str, Any] | None = None) -> dict[str, Any]:
        if kind not in MEMORY_KINDS:
            raise WorldModelError(f"unknown memory kind: {kind}")
        row = {
            "id": f"m_{uuid.uuid4().hex[:12]}", "kind": kind,
            "text": text[:8000], "scope": scope[:120],
            "source": source[:120], "confidence": confidence,
            "meta": dict(meta or {}), "at": _now(),
            "invalidated_by": "",
        }
        self.entries.append(row)
        return dict(row)

    def recall(self, query: str = "", *, kind: str | None = None,
               scope: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        terms = [t for t in (query or "").lower().split() if t]
        out = []
        for row in self.entries:
            if row.get("invalidated_by"):
                continue
            if kind and row["kind"] != kind:
                continue
            if scope and row.get("scope") not in (scope, "global"):
                continue
            hay = (row["text"] + " " + json.dumps(row.get("meta") or {})).lower()
            if terms and not all(t in hay for t in terms):
                continue
            out.append(dict(row))
        out.sort(key=lambda r: r["at"], reverse=True)
        return out[:limit]

    def invalidate(self, entry_id: str, reason: str) -> bool:
        for row in self.entries:
            if row["id"] == entry_id:
                row["invalidated_by"] = reason[:500]
                return True
        return False

    def timeline(self, limit: int = 100) -> list[dict[str, Any]]:
        return sorted((dict(r) for r in self.entries),
                      key=lambda r: r["at"])[-limit:]

    def to_dict(self) -> dict[str, Any]:
        return {"version": 1, "name": self.name, "entries": self.entries}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryFabric":
        mf = cls(str(data.get("name") or "project"))
        mf.entries = [dict(r) for r in data.get("entries") or []
                      if isinstance(r, dict) and r.get("id")]
        return mf

    def save(self, path: str | os.PathLike) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | os.PathLike) -> "MemoryFabric":
        p = Path(path)
        try:
            if p.stat().st_size > 16 * 1024 * 1024:
                raise WorldModelError("memory file is too large")
            data = json.loads(p.read_text("utf-8"))
        except WorldModelError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise WorldModelError(f"could not load memory: {exc}") from exc
        return cls.from_dict(data)
