"""cgroup v2 surface.

Detection is always safe. Scope creation is best-effort and requires write
access to a delegated cgroup subtree; when that is absent, the caller gets an
explicit error and must not claim cgroup enforcement.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path("/sys/fs/cgroup")


class CgroupError(Exception):
    pass


def detect() -> dict[str, Any]:
    return {
        "v2": (ROOT / "cgroup.controllers").is_file(),
        "writable": os.access(ROOT, os.W_OK),
        "root": str(ROOT),
        "controllers": _read("cgroup.controllers"),
    }


def _read(name: str) -> list[str]:
    try:
        return (ROOT / name).read_text().split()
    except OSError:
        return []


@dataclass
class CgroupScope:
    path: str
    memory_max: int | None = None
    pids_max: int | None = None
    created: bool = False
    notes: list[str] = field(default_factory=list)

    def set_memory(self, max_bytes: int) -> None:
        self._write("memory.max", str(int(max_bytes)))

    def set_pids(self, max_pids: int) -> None:
        self._write("pids.max", str(int(max_pids)))

    def add_pid(self, pid: int) -> None:
        self._write("cgroup.procs", str(int(pid)))

    def _write(self, name: str, value: str) -> None:
        try:
            (Path(self.path) / name).write_text(value + "\n")
        except OSError as exc:
            raise CgroupError(f"could not write {name}: {exc}") from exc

    def close(self) -> None:
        try:
            os.rmdir(self.path)
            self.created = False
        except OSError as exc:
            self.notes.append(f"could not remove scope: {exc}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def create_scope(name: str | None = None, *, memory_max: int | None = None,
                 pids_max: int | None = None) -> CgroupScope:
    info = detect()
    if not info["v2"]:
        raise CgroupError("cgroup v2 is not available")
    if not info["writable"]:
        raise CgroupError(
            "the cgroup root is not writable; no delegated cgroup is available")
    path = ROOT / f"reverseai-{name or uuid.uuid4().hex[:8]}"
    try:
        path.mkdir()
    except OSError as exc:
        raise CgroupError(f"could not create cgroup scope: {exc}") from exc
    scope = CgroupScope(str(path), memory_max, pids_max, True)
    try:
        if memory_max:
            scope.set_memory(memory_max)
        if pids_max:
            scope.set_pids(pids_max)
    except CgroupError:
        scope.close()
        raise
    return scope
