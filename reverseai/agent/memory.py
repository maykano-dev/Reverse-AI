"""Long-term memory — durable notes the agent can write and recall.

Inspired by the "remember what matters" layer in personal agents (Xiryn, Claude
Code, OpenCode). Memory is deliberately small and human-editable: a JSON file
of notes with ids, tags, and source. It never stores secrets automatically; the
model must choose to remember something, and the UI can inspect/delete it.

The store is thread-safe and writes atomically so a crash cannot corrupt it.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any


class MemoryStore:
    def __init__(self, path: str | os.PathLike) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._notes: list[dict[str, Any]] = self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        notes = data.get("notes") if isinstance(data, dict) else data
        return [n for n in notes or [] if isinstance(n, dict) and n.get("text")]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "notes": self._notes}, indent=2)
        fd, tmp = tempfile.mkstemp(prefix=".memory-", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # -- API ---------------------------------------------------------------
    def add(self, text: str, tags: list[str] | None = None,
            source: str = "agent") -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise ValueError("memory text is empty")
        note = {
            "id": f"mem_{uuid.uuid4().hex[:10]}",
            "text": text[:4000],
            "tags": [t.strip()[:40] for t in (tags or []) if t and t.strip()][:12],
            "source": source[:80],
            "created_at": time.time(),
        }
        with self._lock:
            self._notes.append(note)
            self._save()
        return dict(note)

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(n) for n in self._notes]

    def search(self, query: str = "", limit: int = 20) -> list[dict[str, Any]]:
        terms = [t for t in (query or "").lower().split() if t]
        with self._lock:
            notes = [dict(n) for n in self._notes]
        if not terms:
            return notes[-limit:]
        scored: list[tuple[int, dict[str, Any]]] = []
        for n in notes:
            hay = (n.get("text", "") + " " + " ".join(n.get("tags", []))).lower()
            score = sum(1 for t in terms if t in hay)
            if score:
                scored.append((score, n))
        scored.sort(key=lambda x: (x[0], x[1].get("created_at", 0)), reverse=True)
        return [n for _, n in scored[:limit]]

    def delete(self, note_id: str) -> bool:
        with self._lock:
            before = len(self._notes)
            self._notes = [n for n in self._notes if n.get("id") != note_id]
            changed = len(self._notes) != before
            if changed:
                self._save()
        return changed

    def clear(self) -> None:
        with self._lock:
            self._notes = []
            self._save()

    def prompt_context(self, limit: int = 40) -> str:
        """A compact block injected into the system prompt."""
        notes = self.all()[-limit:]
        if not notes:
            return ""
        lines = ["Long-term memory (notes from earlier conversations):"]
        for n in notes:
            tags = f" [{', '.join(n['tags'])}]" if n.get("tags") else ""
            lines.append(f"- ({n['id']}) {n['text']}{tags}")
        lines.append("Use these when relevant; do not repeat them to the user verbatim.")
        return "\n".join(lines)


def default_memory_path() -> Path:
    home = os.environ.get("REVERSEAI_HOME")
    base = Path(home) if home else Path.home() / ".reverseai"
    return base / "memory.json"
