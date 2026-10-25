"""Workspace checkpoints and reviewable undo.

A modification should never be a one-way door. Before a write, the agent can
snapshot the workspace into a content-addressed tar plus a manifest of hashes.
The user can list checkpoints, see what changed, and restore one.

Restore is deliberately conservative: absolute paths, ``..``, symlinks, hard
links, and device nodes are refused. Extraction writes regular files only, under
the destination root, so a malicious archive cannot escape.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

MAX_FILES = 4000
MAX_BYTES = 64 * 1024 * 1024
MAX_DIFF_BYTES = 64 * 1024


class CheckpointError(Exception):
    pass


@dataclass
class FileEntry:
    path: str
    size: int
    sha256: str
    mode: int = 0o644

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Checkpoint:
    id: str
    label: str
    note: str
    created_at: float
    root: str
    files: list[FileEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "note": self.note,
            "created_at": self.created_at,
            "root": self.root,
            "files": [f.to_dict() for f in self.files],
        }

    @property
    def manifest(self) -> dict[str, FileEntry]:
        return {f.path: f for f in self.files}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_rel(path: str) -> str:
    p = Path(path)
    if p.is_absolute() or ".." in p.parts or str(p) in ("", "."):
        raise CheckpointError(f"unsafe path: {path!r}")
    return str(p)


def _iter_files(root: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    for base, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not Path(base, d).is_symlink()]
        for name in files:
            p = Path(base, name)
            if p.is_symlink() or not p.is_file():
                continue
            try:
                rel = str(p.relative_to(root))
            except ValueError:
                continue
            out.append((rel, p))
            if len(out) > MAX_FILES:
                raise CheckpointError(f"workspace has more than {MAX_FILES} files")
    return out


def _manifest(root: Path) -> tuple[list[FileEntry], int]:
    entries: list[FileEntry] = []
    total = 0
    for rel, p in _iter_files(root):
        try:
            data = p.read_bytes()
        except OSError as exc:
            raise CheckpointError(f"could not read {rel}: {exc}") from exc
        total += len(data)
        if total > MAX_BYTES:
            raise CheckpointError(f"workspace exceeds {MAX_BYTES} bytes")
        entries.append(FileEntry(rel, len(data), _sha256(data),
                                 int(p.stat().st_mode & 0o777)))
    entries.sort(key=lambda e: e.path)
    return entries, total


class CheckpointStore:
    def __init__(self, directory: str | os.PathLike | None = None,
                 workspace: str | os.PathLike | None = None) -> None:
        self.dir = Path(directory) if directory else Path(".reverseai-checkpoints")
        self.workspace = Path(workspace).resolve() if workspace else None

    def _root(self) -> Path:
        if self.workspace is None:
            raise CheckpointError("no workspace configured for checkpoints")
        return self.workspace

    def create(self, label: str = "checkpoint", note: str = "") -> Checkpoint:
        root = self._root()
        if not root.is_dir():
            raise CheckpointError(f"workspace does not exist: {root}")
        entries, _ = _manifest(root)
        cid = "cp_" + hashlib.sha256(
            (str(time.time()) + label + root.as_posix()).encode()).hexdigest()[:16]
        self.dir.mkdir(parents=True, exist_ok=True)
        archive = self.dir / f"{cid}.tar.gz"
        manifest_path = self.dir / f"{cid}.json"
        fd, tmp = tempfile.mkstemp(prefix=".cp-", dir=str(self.dir))
        os.close(fd)
        try:
            with tarfile.open(tmp, "w:gz") as tar:
                for rel, p in _iter_files(root):
                    tar.add(p, arcname=rel, recursive=False)
            os.replace(tmp, archive)
        except (OSError, tarfile.TarError) as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise CheckpointError(f"could not create checkpoint: {exc}") from exc
        cp = Checkpoint(cid, label, note[:2000], time.time(), str(root), entries)
        manifest_path.write_text(json.dumps(cp.to_dict(), indent=2), encoding="utf-8")
        return cp

    def list(self) -> list[Checkpoint]:
        out: list[Checkpoint] = []
        if not self.dir.is_dir():
            return out
        for p in sorted(self.dir.glob("cp_*.json"), reverse=True):
            try:
                data = json.loads(p.read_text("utf-8"))
                out.append(Checkpoint(
                    id=str(data["id"]), label=str(data.get("label", "")),
                    note=str(data.get("note", "")),
                    created_at=float(data.get("created_at", 0)),
                    root=str(data.get("root", "")),
                    files=[FileEntry(**f) for f in data.get("files") or []],
                ))
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
        return out

    def _load(self, cid: str) -> Checkpoint:
        if not (cid.startswith("cp_") and all(c.isalnum() or c in "_-" for c in cid)):
            raise CheckpointError("invalid checkpoint id")
        p = self.dir / f"{cid}.json"
        try:
            data = json.loads(p.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CheckpointError(f"checkpoint not found: {cid}") from exc
        try:
            return Checkpoint(
                id=str(data["id"]), label=str(data.get("label", "")),
                note=str(data.get("note", "")),
                created_at=float(data.get("created_at", 0)),
                root=str(data.get("root", "")),
                files=[FileEntry(**f) for f in data.get("files") or []],
            )
        except (ValueError, TypeError, KeyError) as exc:
            raise CheckpointError(f"bad checkpoint manifest: {exc}") from exc

    def diff(self, cid: str, current: bool = True) -> dict[str, Any]:
        cp = self._load(cid)
        old = cp.manifest
        new: dict[str, FileEntry] = {}
        if current:
            entries, _ = _manifest(self._root())
            new = {e.path: e for e in entries}
        else:
            new = old
        added = sorted(set(new) - set(old))
        removed = sorted(set(old) - set(new))
        changed = sorted(k for k in set(old) & set(new)
                         if old[k].sha256 != new[k].sha256)
        return {
            "checkpoint": cp.to_dict(),
            "added": added,
            "removed": removed,
            "changed": changed,
            "summary": (f"{len(added)} added, {len(removed)} removed, "
                        f"{len(changed)} changed"),
        }

    def review(self, cid: str) -> dict[str, Any]:
        """Return a bounded unified diff between a checkpoint and the workspace."""
        diff = self.diff(cid, current=True)
        cp = self._load(cid)
        root = self._root()
        old = cp.manifest
        chunks: list[str] = []
        used = 0
        for path in diff["changed"] + diff["added"]:
            try:
                new_data = (root / path).read_bytes()
            except OSError:
                continue
            old_data = b""
            if path in old:
                try:
                    with tarfile.open(self.dir / f"{cid}.tar.gz", "r:gz") as tar:
                        info = tar.getmember(path)
                        if info.size <= MAX_DIFF_BYTES:
                            member = tar.extractfile(info)
                            old_data = member.read() if member else b""
                except (OSError, tarfile.TarError, KeyError):
                    old_data = b""
            if len(old_data) > MAX_DIFF_BYTES or len(new_data) > MAX_DIFF_BYTES:
                chunks.append(f"--- {path}\n+++ {path}\n(binary or large file changed)")
                continue
            try:
                old_text = old_data.decode("utf-8")
                new_text = new_data.decode("utf-8")
            except UnicodeDecodeError:
                chunks.append(f"--- {path}\n+++ {path}\n(binary file changed)")
                continue
            block = "".join(difflib.unified_diff(
                old_text.splitlines(True), new_text.splitlines(True),
                fromfile=f"a/{path}", tofile=f"b/{path}"))
            if used + len(block) > MAX_DIFF_BYTES:
                chunks.append("... diff truncated ...")
                break
            chunks.append(block)
            used += len(block)
        diff["diff"] = "".join(chunks)
        return diff

    def restore(self, cid: str, *, overwrite: bool = False) -> dict[str, Any]:
        cp = self._load(cid)
        root = self._root()
        archive = self.dir / f"{cid}.tar.gz"
        if not archive.is_file():
            raise CheckpointError(f"checkpoint archive missing: {cid}")
        restored: list[str] = []
        try:
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar.getmembers():
                    if not member.isfile():
                        # Refuse symlinks, devices, directories with odd modes.
                        continue
                    try:
                        rel = _safe_rel(member.name)
                    except CheckpointError:
                        # A malicious member is ignored, never extracted.
                        continue
                    dest = (root / rel).resolve()
                    if not str(dest).startswith(str(root.resolve()) + os.sep):
                        continue
                    if dest.exists() and not overwrite:
                        raise CheckpointError(
                            f"refusing to overwrite {rel}; pass overwrite=true")
                    if member.size > MAX_BYTES:
                        continue
                    src = tar.extractfile(member)
                    if src is None:
                        continue
                    data = src.read(MAX_BYTES + 1)
                    if len(data) > MAX_BYTES:
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    try:
                        os.chmod(dest, member.mode & 0o777)
                    except OSError:
                        pass
                    restored.append(rel)
        except (OSError, tarfile.TarError) as exc:
            raise CheckpointError(f"could not restore checkpoint: {exc}") from exc
        return {"checkpoint": cp.to_dict(), "restored": restored,
                "summary": f"restored {len(restored)} file(s)"}
