"""Durable behavioral corpora.

A one-off test is easy to game. A corpus captured from the original program is a
regression suite that future changes must keep passing. This module records the
original behavior for a set of inputs, stores it by target SHA-256, and can load
it as negative controls for ``verify_modification``.

Everything executed here goes through the sandbox. If the host cannot isolate the
target, capture refuses rather than running it on the host.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..sandbox import SandboxPolicy
from .difftest import InputCase, generate_corpus, run_differential


class CorpusError(Exception):
    pass


@dataclass
class CorpusRecord:
    target_sha256: str
    created_at: float = field(default_factory=time.time)
    goal: str = ""
    source: str = "capture_behavior_corpus"
    cases: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def target_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError as exc:
        raise CorpusError(f"could not hash target: {exc}") from exc
    return h.hexdigest()


def default_corpus_dir() -> Path:
    store = os.environ.get("REVERSEAI_STORE", "").strip()
    base = Path(store) if store else Path.home() / ".reverseai"
    return base / "corpora"


class CorpusStore:
    def __init__(self, directory: str | os.PathLike | None = None) -> None:
        self.dir = Path(directory) if directory else default_corpus_dir()

    def path_for(self, sha: str) -> Path:
        if not (isinstance(sha, str) and len(sha) == 64
                and all(c in "0123456789abcdef" for c in sha.lower())):
            raise CorpusError("invalid target hash")
        return self.dir / f"{sha.lower()}.json"

    def save(self, sha: str, cases: list[InputCase], goal: str = "",
             source: str = "capture_behavior_corpus") -> Path:
        if not cases:
            raise CorpusError("refusing to save an empty corpus")
        path = self.path_for(sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = CorpusRecord(
            target_sha256=sha.lower(), goal=goal, source=source,
            cases=[c.to_dict() for c in cases],
        )
        fd, tmp = tempfile.mkstemp(prefix=".corpus-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(record.to_dict(), fh, indent=2)
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return path

    def load(self, sha: str) -> list[InputCase]:
        path = self.path_for(sha)
        try:
            if path.stat().st_size > 8 * 1024 * 1024:
                return []
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = data.get("cases") if isinstance(data, dict) else data
        out: list[InputCase] = []
        for row in rows or []:
            try:
                out.append(InputCase.from_dict(row).normalized())
            except Exception:
                continue
        return out

    def list(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self.dir.is_dir():
            return out
        for p in sorted(self.dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(p.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or not data.get("target_sha256"):
                continue
            out.append({
                "target_sha256": data.get("target_sha256"),
                "created_at": data.get("created_at"),
                "goal": data.get("goal", ""),
                "cases": len(data.get("cases") or []),
                "path": str(p),
            })
        return out

    def summary(self, sha: str) -> dict[str, Any]:
        path = self.path_for(sha)
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {
            "target_sha256": data.get("target_sha256"),
            "created_at": data.get("created_at"),
            "goal": data.get("goal"),
            "cases": len(data.get("cases") or []),
            "path": str(path),
        }

    def delete(self, sha: str) -> bool:
        try:
            self.path_for(sha).unlink()
            return True
        except (OSError, CorpusError):
            return False


def capture_corpus(
    original_path: str,
    cases: list[InputCase] | None = None,
    *,
    policy: SandboxPolicy | None = None,
    output_files: list[str] | None = None,
    timeout_seconds: float = 10.0,
) -> tuple[list[InputCase], dict[str, Any]]:
    """Run the original over the corpus and convert its behavior to expectations.

    The returned cases are regression controls: ``same_as_original`` plus the
    exact exit/stdout/stderr/output-file behavior observed from the original.
    """
    source_cases = [c.normalized() for c in (cases or generate_corpus())]
    if not source_cases:
        raise CorpusError("empty corpus")
    report = run_differential(
        original_path, original_path, source_cases, policy=policy,
        output_files=output_files, timeout_seconds=timeout_seconds)
    if not report.ran:
        raise CorpusError(f"sandbox unavailable, refusing to capture: {report.error}")

    by_name: dict[str, InputCase] = {c.name: c for c in source_cases}
    captured: list[InputCase] = []
    for result in report.cases:
        source = by_name.get(result.name)
        if source is None:
            continue
        snap = result.original
        expect: dict[str, Any] = {
            "same_as_original": True,
            "stdout": snap.stdout,
            "stderr": snap.stderr,
        }
        if snap.exit_code is not None:
            expect["exit_code"] = snap.exit_code
        files: dict[str, str] = {}
        for name, meta in (snap.output_files or {}).items():
            if meta.get("text") is not None:
                files[name] = meta["text"]
            elif meta.get("sha256"):
                files[name] = meta["sha256"]
        if files:
            expect["output_files"] = files
        captured.append(InputCase(
            source.name, source.args, source.stdin, source.files, expect,
        ).normalized())
    if not captured:
        raise CorpusError("capture produced no cases")
    summary = {
        "summary": report.summary,
        "cases": len(captured),
        "matched": report.matched,
        "differed": report.differed,
    }
    return captured, summary


def load_for_target(store: CorpusStore | None, target_path: str,
                    exclude: list[str] | None = None,
                    prefix: str = "corpus") -> list[InputCase]:
    if store is None:
        return []
    try:
        sha = target_sha256(target_path)
    except CorpusError:
        return []
    exclude_set = set(exclude or [])
    out: list[InputCase] = []
    for case in store.load(sha):
        if case.name in exclude_set:
            continue
        case.name = f"{prefix}/{case.name}"
        out.append(case)
    return out
