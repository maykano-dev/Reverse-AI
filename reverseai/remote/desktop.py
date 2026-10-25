"""A local desktop-session broker and loopback control listener.

The broker manages session records and an allowlisted action vocabulary. It does
not inject keyboard or mouse input and it does not open a VNC port. A future
backend must implement the same action contract and pass the approval gate.

The listener binds loopback only and requires a bearer token. It is not started
by default.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..security.approvals import ApprovalError, ApprovalLedger
from ..security.capabilities import CapabilityDenied, CapabilityPolicy
from ..security.gate import ActionGate, GateError

MAX_TTL = 3600
SAFE_ACTIONS = {"status", "list", "close", "screenshot"}
GATED_ACTIONS = {"takeover", "focus", "refresh"}
UNSUPPORTED = {"type", "click", "key", "drag", "paste", "shell", "exec"}


@dataclass
class DesktopSession:
    id: str
    name: str
    backend: str = "interface-only"
    status: str = "open"          # open | closed | expired
    actions: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    workspace: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at


class DesktopBroker:
    def __init__(self, *, policy: CapabilityPolicy | None = None,
                 ledger: ApprovalLedger | None = None,
                 root: str | os.PathLike | None = None,
                 audit_path: str | os.PathLike | None = None) -> None:
        self.policy = policy or CapabilityPolicy()
        self.ledger = ledger
        self.root = Path(root or Path.home() / ".reverseai" / "desktop-sessions")
        self.audit_path = Path(audit_path) if audit_path else self.root / "audit.jsonl"
        self.sessions: dict[str, DesktopSession] = {}
        self._lock = threading.Lock()

    def _require(self) -> None:
        self.policy.require("desktop_workstation")

    def _audit(self, row: dict[str, Any]) -> None:
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": time.time(), **row}) + "\n")
        except OSError:
            pass

    def open(self, name: str = "session", *,
             actions: list[str] | None = None, ttl: int = 900) -> DesktopSession:
        self._require()
        ttl = max(60, min(int(ttl or 900), MAX_TTL))
        allowed = [a for a in (actions or sorted(SAFE_ACTIONS | GATED_ACTIONS))
                   if a in SAFE_ACTIONS | GATED_ACTIONS]
        sid = "ds_" + uuid.uuid4().hex[:12]
        workspace = self.root / sid
        workspace.mkdir(parents=True, exist_ok=True)
        session = DesktopSession(
            sid, str(name)[:200], "interface-only", "open", allowed,
            time.time(), time.time() + ttl, str(workspace),
            {"input_injection": False, "display": "none"})
        with self._lock:
            self.sessions[sid] = session
        (workspace / "session.json").write_text(json.dumps(session.to_dict(), indent=2),
                                                encoding="utf-8")
        self._audit({"event": "open", "session": sid, "name": session.name})
        return session

    def list(self) -> list[dict[str, Any]]:
        self._require()
        out = []
        for s in self.sessions.values():
            if s.expired and s.status == "open":
                s.status = "expired"
            out.append(s.to_dict())
        return out

    def get(self, session_id: str) -> DesktopSession | None:
        self._require()
        return self.sessions.get(session_id)

    def close(self, session_id: str) -> bool:
        self._require()
        s = self.sessions.get(session_id)
        if s is None:
            return False
        s.status = "closed"
        self._audit({"event": "close", "session": session_id})
        return True

    def execute(self, session_id: str, action: str,
                approval_token: str | None = None) -> dict[str, Any]:
        self._require()
        s = self.sessions.get(session_id)
        if s is None:
            raise KeyError("unknown desktop session")
        if s.expired:
            s.status = "expired"
            raise PermissionError("desktop session has expired")
        action = str(action or "").strip().lower()
        if action in UNSUPPORTED:
            self._audit({"event": "refused", "session": session_id,
                         "action": action, "why": "no input backend"})
            raise PermissionError(
                "input injection is not implemented; this listener has no keyboard "
                "or mouse backend")
        if action not in s.actions:
            raise PermissionError(f"action {action!r} is not allowed for this session")
        if action in GATED_ACTIONS:
            if self.ledger is None:
                raise PermissionError("gated desktop actions require an approval ledger")
            gate = ActionGate(self.policy, self.ledger,
                              self.audit_path)
            try:
                gate.authorize("desktop_workstation", f"desktop.{action}",
                               session_id, approval_token)
            except (CapabilityDenied, GateError, ApprovalError) as exc:
                self._audit({"event": "refused", "session": session_id,
                             "action": action, "why": str(exc)})
                raise PermissionError(str(exc)) from exc
        result = {"session": session_id, "action": action, "ok": True,
                  "backend": s.backend, "display": "none",
                  "input_injection": False}
        if action == "screenshot":
            result.update({"screenshot": None,
                           "reason": "no display backend is configured"})
        if action == "status":
            result.update({"status": s.status, "expires_at": s.expires_at})
        self._audit({"event": "action", "session": session_id, "action": action})
        return result


class _Handler(BaseHTTPRequestHandler):
    server_version = "ReverseAIDesktop/1"

    def log_message(self, fmt, *args):  # noqa: A003
        return

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _auth(self) -> bool:
        token = getattr(self.server, "desk_token", "")
        auth = self.headers.get("Authorization", "")
        if not token:
            self._json(503, {"error": "desktop listener is not configured"})
            return False
        if auth != f"Bearer {token}":
            self._json(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self):  # noqa: N802
        if not self._auth():
            return
        broker: DesktopBroker = self.server.broker
        if self.path == "/sessions":
            return self._json(200, {"sessions": broker.list()})
        return self._json(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._auth():
            return
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length > 64 * 1024:
                return self._json(413, {"error": "body too large"})
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "invalid JSON"})
        broker: DesktopBroker = self.server.broker
        try:
            if self.path == "/open":
                s = broker.open(str(body.get("name") or "session"),
                                actions=body.get("actions"), ttl=int(body.get("ttl", 900)))
                return self._json(200, s.to_dict())
            if self.path == "/action":
                out = broker.execute(str(body.get("session") or ""),
                                     str(body.get("action") or ""),
                                     body.get("approval_token"))
                return self._json(200, out)
            if self.path == "/close":
                return self._json(200, {"closed": broker.close(
                    str(body.get("session") or ""))})
        except PermissionError as exc:
            return self._json(403, {"error": str(exc)})
        except (KeyError, ValueError) as exc:
            return self._json(400, {"error": str(exc)})
        except CapabilityDenied as exc:
            return self._json(403, {"error": str(exc)})
        return self._json(404, {"error": "not found"})


class DesktopControlServer:
    def __init__(self, broker: DesktopBroker, token: str,
                 host: str = "127.0.0.1", port: int = 0) -> None:
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("the desktop listener must bind loopback only")
        if not token or len(token) < 16:
            raise ValueError("desktop listener token must be at least 16 characters")
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.broker = broker
        self.httpd.desk_token = token
        self.address = self.httpd.server_address
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.thread:
            self.thread.join(timeout=3)
