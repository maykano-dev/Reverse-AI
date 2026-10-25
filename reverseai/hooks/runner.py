"""Hook manifests and a sandboxed runner.

A hook is a command run on a named event (for example ``tool.before``). It can
observe a JSON payload on stdin and return JSON on stdout. Hooks never inherit
the host environment, never get network by default, and are refused unless the
operator enables the ``hooks`` capability and signs the manifest.
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

from ..sandbox import SandboxPolicy, create_sandbox
from ..security.capabilities import CapabilityDenied, CapabilityPolicy

EVENTS = {"tool.before", "tool.after", "turn.start", "turn.end",
          "verification.before", "verification.after", "delivery.before"}


class HookError(Exception):
    pass


@dataclass
class HookManifest:
    name: str
    event: str
    command: list[str]
    timeout_seconds: float = 10.0
    permissions: list[str] = field(default_factory=list)
    signature: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> list[str]:
        problems = []
        if not self.name:
            problems.append("missing name")
        if self.event not in EVENTS:
            problems.append(f"unknown event: {self.event}")
        if not self.command:
            problems.append("missing command")
        if any(str(x).startswith((";", "|", "&", ">", "<")) for x in self.command):
            problems.append("shell metacharacters are not allowed")
        if not (0 < self.timeout_seconds <= 60):
            problems.append("timeout must be 0-60 seconds")
        return problems


def sign_manifest(manifest: dict[str, Any], key: str | None = None) -> str:
    key = key or os.environ.get("REVERSEAI_HOOK_KEY", "")
    if not key:
        raise HookError("REVERSEAI_HOOK_KEY is required to sign a hook")
    body = {k: v for k, v in manifest.items() if k != "signature"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(key.encode(), raw, hashlib.sha256).hexdigest()


def verify_manifest(manifest: dict[str, Any], key: str | None = None) -> bool:
    sig = str(manifest.get("signature") or "")
    if not sig:
        return False
    try:
        return hmac.compare_digest(sig, sign_manifest(manifest, key))
    except HookError:
        return False


@dataclass
class HookResult:
    name: str
    event: str
    ok: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""
    duration_s: float = 0.0
    isolation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class HookRegistry:
    def __init__(self, path: str | os.PathLike | None = None) -> None:
        self.path = Path(path) if path else Path.home() / ".reverseai" / "hooks.json"
        self.manifests: dict[str, HookManifest] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for row in data.get("hooks") or []:
            try:
                manifest = HookManifest(**row)
                if not manifest.validate():
                    self.manifests[manifest.name] = manifest
            except (TypeError, ValueError):
                continue

    def add(self, manifest: HookManifest, *, key: str | None = None,
            require_signature: bool = True) -> None:
        problems = manifest.validate()
        if problems:
            raise HookError("; ".join(problems))
        if require_signature:
            if not verify_manifest(manifest.to_dict(), key):
                raise HookError("hook manifest is not signed or signature is invalid")
        self.manifests[manifest.name] = manifest
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"version": 1, "hooks": [
            m.to_dict() for m in self.manifests.values()]}, indent=2),
            encoding="utf-8")

    def for_event(self, event: str) -> list[HookManifest]:
        return [m for m in self.manifests.values() if m.event == event]


class HookRunner:
    def __init__(self, *, policy: CapabilityPolicy | None = None,
                 audit_path: str | os.PathLike | None = None) -> None:
        self.policy = policy or CapabilityPolicy()
        self.audit_path = Path(audit_path) if audit_path else None

    def _audit(self, row: dict[str, Any]) -> None:
        if self.audit_path is None:
            return
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": time.time(), **row}) + "\n")
        except OSError:
            pass

    def run(self, manifest: HookManifest, payload: dict[str, Any], *,
            policy: SandboxPolicy | None = None) -> HookResult:
        try:
            self.policy.require("hooks")
        except CapabilityDenied as exc:
            return HookResult(manifest.name, manifest.event, False,
                              error=str(exc))
        problems = manifest.validate()
        if problems:
            return HookResult(manifest.name, manifest.event, False,
                              error="; ".join(problems))
        base = policy or SandboxPolicy(allow_untrusted_execution=True,
                                       timeout_seconds=manifest.timeout_seconds)
        from dataclasses import replace

        base = replace(base, allow_untrusted_execution=True,
                       timeout_seconds=manifest.timeout_seconds)
        try:
            sandbox = create_sandbox(base)
        except Exception as exc:
            return HookResult(manifest.name, manifest.event, False,
                              error=f"no isolating sandbox: {exc}")
        start = time.monotonic()
        result = sandbox.run(list(manifest.command), base,
                             stdin=json.dumps(payload).encode())
        out = HookResult(
            manifest.name, manifest.event, bool(result.ok),
            result.exit_code, result.stdout_text()[:8000],
            result.stderr_text()[:4000], result.error or "",
            round(time.monotonic() - start, 3),
            result.isolation.to_dict() if result.isolation else {})
        self._audit({"event": "hook", "name": manifest.name,
                     "hook_event": manifest.event, "ok": out.ok})
        return out
