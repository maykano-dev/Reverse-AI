"""A conservative extension protocol.

An extension is third-party code. The registry records a manifest, declared
permissions, tests, and a security-review state. It does not import or execute
an extension automatically. Promotion requires a reviewed, signed manifest and an
explicit operator action.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REQUIRED = ("name", "version", "entrypoint", "permissions", "capabilities",
            "tests", "security_review")


@dataclass
class ExtensionManifest:
    name: str
    version: str
    entrypoint: str
    permissions: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    security_review: str = "pending"   # pending | reviewed | rejected
    signature: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def manifest_problems(manifest: dict[str, Any]) -> list[str]:
    problems = [f"missing {k}" for k in REQUIRED if not manifest.get(k)]
    if manifest.get("security_review") not in ("reviewed", "pending", "rejected"):
        problems.append("invalid security_review")
    if manifest.get("permissions") and not isinstance(manifest["permissions"], list):
        problems.append("permissions must be a list")
    if manifest.get("entrypoint", "").startswith(("/", "..")):
        problems.append("entrypoint must be relative")
    return problems


def sign_manifest(manifest: dict[str, Any], key: str | None = None) -> str:
    key = key or os.environ.get("REVERSEAI_EXTENSION_KEY", "")
    if not key:
        raise ValueError("REVERSEAI_EXTENSION_KEY is required to sign an extension")
    body = {k: v for k, v in manifest.items() if k != "signature"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()


def verify_manifest(manifest: dict[str, Any], key: str | None = None) -> bool:
    sig = str(manifest.get("signature") or "")
    if not sig:
        return False
    try:
        return hmac.compare_digest(sig, sign_manifest(manifest, key))
    except ValueError:
        return False


class ExtensionRegistry:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.items: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for row in data.get("extensions") or []:
            if isinstance(row, dict) and row.get("name"):
                self.items[row["name"]] = row

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"version": 1,
                                        "extensions": list(self.items.values())},
                                       indent=2), encoding="utf-8")

    def register(self, manifest: dict[str, Any], *,
                 require_signature: bool = True) -> dict[str, Any]:
        problems = manifest_problems(manifest)
        if problems:
            raise ValueError("; ".join(problems))
        if require_signature and not verify_manifest(manifest):
            raise ValueError("extension manifest is not signed or the signature is invalid")
        if manifest.get("security_review") != "reviewed":
            raise ValueError("extension has not passed security review")
        row = dict(manifest)
        row["registered_at"] = time.time()
        self.items[row["name"]] = row
        self._save()
        return row

    def list(self) -> list[dict[str, Any]]:
        return list(self.items.values())

    def get(self, name: str) -> dict[str, Any] | None:
        return self.items.get(name)
