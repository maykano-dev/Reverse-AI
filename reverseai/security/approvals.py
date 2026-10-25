"""Human-in-the-loop approvals for irreversible or high-risk actions.

The capability policy answers "is this feature allowed to exist?" This module
answers the narrower question: "did a human approve *this* action, for *this*
scope, right now?" An approval is a short-lived, HMAC-signed, single-use token.
It is deliberately not a password and not a session: it cannot be replayed, it
cannot authorize a different action, and it expires.

Nothing in this release executes a payment, a remote command, or a desktop
action. The ledger exists so a future implementation has a real gate to call
before it does anything irreversible.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_MASTER = "REVERSEAI_APPROVAL_KEY"
DEFAULT_TTL = 300.0
MAX_TTL = 3600.0
MAX_USES = 10


class ApprovalError(Exception):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _key(env: dict[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    key = str(source.get(_MASTER, "")).strip()
    if not key:
        raise ApprovalError(
            f"approvals require {_MASTER}; refusing to create an unsigned approval")
    if len(key) < 16:
        raise ApprovalError(f"{_MASTER} must be at least 16 characters")
    return key


@dataclass
class Approval:
    id: str
    action: str
    scope: str
    reason: str
    created_at: float
    expires_at: float
    max_uses: int = 1
    uses: int = 0
    nonce: str = field(default_factory=lambda: secrets.token_hex(8))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ApprovalGrant:
    token: str
    approval: Approval

    def to_dict(self) -> dict[str, Any]:
        return {"token": self.token, "approval": self.approval.to_dict()}


class ApprovalLedger:
    """Issue and consume single-use approvals, with a durable use log."""

    def __init__(self, directory: str | os.PathLike | None = None,
                 env: dict[str, str] | None = None) -> None:
        self.dir = Path(directory) if directory else Path(".reverseai-approvals")
        self._env = env

    @property
    def key(self) -> str:
        return _key(self._env)

    def _sign(self, approval: Approval) -> str:
        body = json.dumps(approval.to_dict(), sort_keys=True,
                          separators=(",", ":")).encode()
        mac = hmac.new(self.key.encode(), body, hashlib.sha256).digest()
        return _b64(body) + "." + _b64(mac)

    def _verify(self, token: str) -> Approval:
        try:
            body_b64, mac_b64 = token.split(".", 1)
            body = _unb64(body_b64)
            mac = _unb64(mac_b64)
        except (ValueError, TypeError) as exc:
            raise ApprovalError("malformed approval token") from exc
        expected = hmac.new(self.key.encode(), body, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected):
            raise ApprovalError("approval signature is invalid")
        try:
            data = json.loads(body)
            approval = Approval(**data)
        except (ValueError, TypeError) as exc:
            raise ApprovalError(f"bad approval payload: {exc}") from exc
        if time.time() > approval.expires_at:
            raise ApprovalError("approval has expired")
        if approval.uses >= approval.max_uses:
            raise ApprovalError("approval has already been used")
        return approval

    def grant(self, action: str, scope: str = "", reason: str = "",
              ttl_seconds: float = DEFAULT_TTL,
              max_uses: int = 1) -> ApprovalGrant:
        action = str(action or "").strip()
        if not action:
            raise ApprovalError("approval needs an action")
        ttl = min(max(float(ttl_seconds or DEFAULT_TTL), 1.0), MAX_TTL)
        uses = min(max(int(max_uses or 1), 1), MAX_USES)
        now = time.time()
        approval = Approval(
            id="ap_" + secrets.token_hex(12), action=action,
            scope=str(scope or ""), reason=str(reason or "")[:2000],
            created_at=now, expires_at=now + ttl, max_uses=uses,
        )
        token = self._sign(approval)
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass
        # Store only the approval metadata and the final token; never a secret.
        (self.dir / f"{approval.id}.json").write_text(json.dumps({
            "approval": approval.to_dict(), "token": token,
        }, indent=2), encoding="utf-8")
        try:
            os.chmod(self.dir / f"{approval.id}.json", 0o600)
        except OSError:
            pass
        return ApprovalGrant(token, approval)

    def consume(self, token: str, action: str, scope: str = "") -> Approval:
        approval = self._verify(token)
        if approval.action != action:
            raise ApprovalError(
                f"approval is for {approval.action!r}, not {action!r}")
        if approval.scope and scope and approval.scope != scope:
            raise ApprovalError("approval scope does not match")
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{approval.id}.json"
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        used = int(data.get("uses", 0) or 0)
        if used >= approval.max_uses:
            raise ApprovalError("approval has already been used")
        approval.uses = used + 1
        data["uses"] = approval.uses
        data["approval"] = approval.to_dict()
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return approval

    def pending(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not self.dir.is_dir():
            return out
        for p in sorted(self.dir.glob("ap_*.json")):
            try:
                data = json.loads(p.read_text("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            approval = data.get("approval") or {}
            if float(approval.get("expires_at", 0)) <= time.time():
                continue
            used = int(data.get("uses", approval.get("uses", 0)) or 0)
            if used >= int(approval.get("max_uses", 1)):
                continue
            out.append(approval)
        return out
