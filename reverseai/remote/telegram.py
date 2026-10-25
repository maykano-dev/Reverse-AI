"""A deliberately small Telegram control channel.

It supports read-only status/jobs/readiness/discovery commands and a pairing
flow. It does not expose a shell, arbitrary file reads, deployments, payments, or
unapproved desktop actions. Every command is rate-limited and audited.

The transport is injectable so the channel can be tested without a bot token or
network access. The real transport is only constructed when the operator enables
the ``remote_control`` capability and supplies a token.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..security.capabilities import CapabilityDenied, CapabilityPolicy


class TelegramError(Exception):
    pass


class TelegramTransport(Protocol):
    def send(self, chat_id: int, text: str) -> None: ...
    def updates(self, offset: int | None = None) -> list[dict[str, Any]]: ...


@dataclass
class TelegramConfig:
    token: str = ""
    allowed_chat_ids: list[int] = field(default_factory=list)
    pairing_code: str = ""
    rate_limit_seconds: float = 2.0
    api_base: str = "https://api.telegram.org"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "TelegramConfig":
        e = env if env is not None else os.environ
        raw = str(e.get("REVERSEAI_TELEGRAM_CHATS", "") or "")
        chats = []
        for part in raw.split(","):
            part = part.strip()
            if part:
                try:
                    chats.append(int(part))
                except ValueError:
                    continue
        return cls(
            token=str(e.get("REVERSEAI_TELEGRAM_TOKEN", "") or ""),
            allowed_chat_ids=chats,
            pairing_code=str(e.get("REVERSEAI_TELEGRAM_PAIRING", "") or ""),
            rate_limit_seconds=float(e.get("REVERSEAI_TELEGRAM_RATE", "2") or 2),
            api_base=str(e.get("REVERSEAI_TELEGRAM_API", "https://api.telegram.org")),
        )


class UrllibTelegramTransport:
    """Real Bot API transport. Only constructed by an explicit operator path."""

    def __init__(self, config: TelegramConfig) -> None:
        if not config.token:
            raise TelegramError("Telegram token is not configured")
        self.config = config

    def _call(self, method: str, payload: dict[str, Any]) -> Any:
        url = f"{self.config.api_base}/bot{self.config.token}/{method}"
        data = urllib.parse.urlencode(payload).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                body = json.loads(r.read())
        except Exception as exc:
            raise TelegramError(f"Telegram request failed: {exc}") from exc
        if not body.get("ok"):
            raise TelegramError(str(body.get("description") or "Telegram error"))
        return body.get("result")

    def send(self, chat_id: int, text: str) -> None:
        self._call("sendMessage", {"chat_id": chat_id, "text": text[:4000]})

    def updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": 20}
        if offset is not None:
            payload["offset"] = offset
        return list(self._call("getUpdates", payload) or [])


class TelegramBot:
    def __init__(self, config: TelegramConfig,
                 transport: TelegramTransport | None = None, *,
                 policy: CapabilityPolicy | None = None,
                 job_summary=None, discover=None, readiness=None,
                 audit_path: str | os.PathLike | None = None,
                 env: dict[str, str] | None = None) -> None:
        self.config = config
        self.policy = policy or CapabilityPolicy(env)
        self.transport = transport
        self.job_summary = job_summary
        self.discover = discover
        self.readiness = readiness
        self.audit_path = Path(audit_path) if audit_path else None
        self.paired: set[int] = set(config.allowed_chat_ids)
        self._last: dict[int, float] = {}
        self.offset: int | None = None

    def _audit(self, row: dict[str, Any]) -> None:
        if self.audit_path is None:
            return
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": time.time(), **row}) + "\n")
        except OSError:
            pass

    def _allowed(self, chat_id: int) -> bool:
        return chat_id in self.paired

    def _rate_ok(self, chat_id: int) -> bool:
        now = time.time()
        last = self._last.get(chat_id, 0.0)
        if now - last < self.config.rate_limit_seconds:
            return False
        self._last[chat_id] = now
        return True

    def handle_text(self, chat_id: int, text: str) -> str:
        try:
            self.policy.require("remote_control")
        except CapabilityDenied as exc:
            self._audit({"event": "capability_refused", "chat": chat_id})
            return f"Remote control is disabled: {exc}"
        if not self._rate_ok(chat_id):
            return "Slow down."
        text = (text or "").strip()
        if text.startswith("/pair"):
            code = text.partition(" ")[2].strip()
            if self.config.pairing_code and code == self.config.pairing_code:
                self.paired.add(chat_id)
                self._audit({"event": "pair", "chat": chat_id})
                return "Paired. Try /help."
            self._audit({"event": "pair_refused", "chat": chat_id})
            return "Pairing code is invalid."
        if not self._allowed(chat_id):
            self._audit({"event": "refused", "chat": chat_id})
            return "This chat is not paired."
        parts = text.split()
        cmd = parts[0].lower().split("@")[0] if parts else ""
        if cmd in ("/start", "/help"):
            return ("ReverseAI read-only channel:\n"
                    "/status  /jobs  /readiness <path>  /discover <path>  /pair <code>\n"
                    "No shell, deployment, payment, or arbitrary file access.")
        if cmd == "/status":
            return "ReverseAI is online. Remote actions are approval-gated."
        if cmd == "/jobs":
            if self.job_summary is None:
                return "No job store is attached."
            rows = self.job_summary(10)
            if not rows:
                return "No jobs."
            return "\n".join(
                f"{r.get('id')}: {r.get('status')} — {str(r.get('goal'))[:80]}"
                for r in rows)
        if cmd in ("/readiness", "/discover"):
            path = " ".join(parts[1:]).strip()
            if not path:
                return f"Usage: {cmd} <path>"
            if cmd == "/readiness":
                if self.readiness is None:
                    return "Readiness service is not attached."
                data = self.readiness(path)
                return json.dumps(data, indent=2)[:3500]
            if self.discover is None:
                return "Discovery service is not attached."
            data = self.discover(path)
            return json.dumps(data, indent=2)[:3500]
        self._audit({"event": "unknown", "chat": chat_id, "cmd": cmd})
        return "Unknown command. Try /help."

    def handle_update(self, update: dict[str, Any]) -> str | None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        text = message.get("text")
        if not isinstance(chat_id, int) or not isinstance(text, str):
            return None
        reply = self.handle_text(chat_id, text)
        self._audit({"event": "message", "chat": chat_id, "cmd": text[:80]})
        if self.transport is not None:
            self.transport.send(chat_id, reply)
        return reply

    def poll_once(self) -> list[str]:
        if self.transport is None:
            raise TelegramError("no transport configured")
        updates = self.transport.updates(self.offset)
        out = []
        for update in updates:
            self.offset = int(update.get("update_id", 0) or 0) + 1
            reply = self.handle_update(update)
            if reply:
                out.append(reply)
        return out

    def require_capability(self) -> None:
        self.policy.require("remote_control")
