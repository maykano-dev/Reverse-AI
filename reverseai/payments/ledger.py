"""Idempotent payment intents behind a capability and approval gate.

The only bundled provider is deterministic and does not move money. A real
provider must implement ``PaymentProvider`` and is still blocked unless the
operator enables ``payments`` and a human supplies a live, scoped approval.

No card number, CVV, or bank credential is accepted by this module.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..security.approvals import ApprovalError, ApprovalLedger
from ..security.capabilities import CapabilityDenied, CapabilityPolicy
from ..security.gate import ActionGate, GateError


class PaymentRefused(Exception):
    pass


@dataclass
class PaymentIntent:
    id: str
    amount_cents: int
    currency: str
    description: str
    scope: str
    idempotency_key: str
    status: str = "created"   # created | approved | charged | failed | refunded
    provider_id: str = ""
    created_at: float = field(default_factory=time.time)
    charged_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PaymentProvider(Protocol):
    name: str

    def charge(self, intent: PaymentIntent) -> dict[str, Any]: ...

    def refund(self, intent: PaymentIntent, amount_cents: int | None = None) -> dict[str, Any]: ...


class HttpPaymentProvider:
    """Operator-supplied payment endpoint.

    The request contains only an intent id, amount, currency, description, and
    idempotency key. It never accepts or sends card data. The transport is
    injectable so tests do not perform a live charge.
    """

    name = "http"

    def __init__(self, endpoint: str, token: str = "",
                 transport: Any = None, timeout: float = 20.0) -> None:
        if not endpoint.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise PaymentRefused("payment endpoint must be HTTPS or loopback")
        self.endpoint = endpoint
        self.token = token
        self.timeout = timeout
        self.transport = transport

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self.transport is not None:
            return self.transport(path, payload)
        import json
        import urllib.request

        req = urllib.request.Request(
            self.endpoint.rstrip("/") + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.token}"} if self.token else {})},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            raise PaymentRefused(f"payment endpoint failed: {exc}") from exc

    def charge(self, intent: PaymentIntent) -> dict[str, Any]:
        return self._post("/charge", {
            "intent_id": intent.id, "amount_cents": intent.amount_cents,
            "currency": intent.currency, "description": intent.description,
            "idempotency_key": intent.idempotency_key,
        })

    def refund(self, intent: PaymentIntent,
               amount_cents: int | None = None) -> dict[str, Any]:
        return self._post("/refund", {
            "intent_id": intent.id,
            "amount_cents": amount_cents or intent.amount_cents,
        })


class MockPaymentProvider:
    """Deterministic provider for tests and dry runs. It moves no money."""

    name = "mock"

    def charge(self, intent: PaymentIntent) -> dict[str, Any]:
        return {"ok": True, "provider": self.name,
                "provider_id": "mock_" + uuid.uuid4().hex[:10],
                "amount_cents": intent.amount_cents, "currency": intent.currency,
                "live": False}

    def refund(self, intent: PaymentIntent,
               amount_cents: int | None = None) -> dict[str, Any]:
        return {"ok": True, "provider": self.name,
                "refunded_cents": amount_cents or intent.amount_cents,
                "live": False}


class PaymentLedger:
    def __init__(self, path: str | os.PathLike | None = None, *,
                 policy: CapabilityPolicy | None = None,
                 ledger: ApprovalLedger | None = None,
                 provider: PaymentProvider | None = None,
                 max_amount_cents: int = 10_000,
                 allowed_currencies: set[str] | None = None,
                 audit_path: str | os.PathLike | None = None) -> None:
        self.path = Path(path or Path.home() / ".reverseai" / "payments.json")
        self.policy = policy or CapabilityPolicy()
        self.approvals = ledger
        self.provider = provider
        self.max_amount_cents = max(1, int(max_amount_cents))
        self.allowed_currencies = {c.upper() for c in
                                   (allowed_currencies or {"USD", "EUR", "GBP"})}
        self.audit_path = Path(audit_path) if audit_path else self.path.with_suffix(".audit.jsonl")
        self.intents: dict[str, PaymentIntent] = {}
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for row in data.get("intents") or []:
            try:
                intent = PaymentIntent(**row)
                self.intents[intent.id] = intent
            except (TypeError, ValueError):
                continue

    def _save(self) -> None:
        import tempfile

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".payments-", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "intents": [
                    i.to_dict() for i in self.intents.values()]}, fh, indent=2)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def _audit(self, row: dict[str, Any]) -> None:
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": time.time(), **row}) + "\n")
        except OSError:
            pass

    def create(self, amount_cents: int, currency: str, description: str, *,
               scope: str = "", idempotency_key: str = "",
               metadata: dict[str, Any] | None = None) -> PaymentIntent:
        try:
            self.policy.require("payments")
        except CapabilityDenied as exc:
            raise PaymentRefused(str(exc)) from exc
        amount = int(amount_cents)
        if amount <= 0:
            raise PaymentRefused("amount must be positive")
        if amount > self.max_amount_cents:
            raise PaymentRefused(
                f"amount exceeds the configured limit of {self.max_amount_cents} cents")
        cur = str(currency or "").upper()
        if cur not in self.allowed_currencies:
            raise PaymentRefused(f"currency {cur!r} is not allowed")
        key = str(idempotency_key or "").strip()
        if key:
            for existing in self.intents.values():
                if existing.idempotency_key == key:
                    return existing
        else:
            key = "auto_" + uuid.uuid4().hex[:12]
        intent = PaymentIntent(
            "pi_" + uuid.uuid4().hex[:12], amount, cur,
            str(description)[:500], str(scope)[:200], key,
            metadata=dict(metadata or {}))
        self.intents[intent.id] = intent
        self._save()
        self._audit({"event": "create", "intent": intent.id,
                     "amount": amount, "currency": cur})
        return intent

    def charge(self, intent_id: str, approval_token: str) -> dict[str, Any]:
        intent = self.intents.get(intent_id)
        if intent is None:
            raise PaymentRefused("unknown payment intent")
        if intent.status == "charged":
            return {"ok": True, "idempotent": True,
                    "intent": intent.to_dict()}
        try:
            self.policy.require("payments")
        except CapabilityDenied as exc:
            raise PaymentRefused(str(exc)) from exc
        if self.provider is None:
            raise PaymentRefused("no payment provider is configured")
        if self.approvals is None:
            raise PaymentRefused("no approval ledger is configured")
        gate = ActionGate(self.policy, self.approvals, self.audit_path)
        try:
            gate.authorize("payments", "payments.charge", intent.scope,
                           approval_token)
        except (CapabilityDenied, GateError, ApprovalError) as exc:
            self._audit({"event": "refused", "intent": intent.id,
                         "why": str(exc)})
            raise PaymentRefused(str(exc)) from exc
        try:
            result = self.provider.charge(intent)
        except Exception as exc:
            intent.status = "failed"
            self._save()
            self._audit({"event": "provider_error", "intent": intent.id,
                         "why": str(exc)})
            raise PaymentRefused(f"provider failed: {exc}") from exc
        if not result.get("ok"):
            intent.status = "failed"
            self._save()
            raise PaymentRefused(str(result.get("error") or "provider refused"))
        intent.status = "charged"
        intent.provider_id = str(result.get("provider_id") or "")
        intent.charged_at = time.time()
        self._save()
        self._audit({"event": "charged", "intent": intent.id,
                     "provider": result.get("provider", ""),
                     "live": bool(result.get("live", False))})
        return {"ok": True, "intent": intent.to_dict(), "provider": result}

    def summary(self) -> dict[str, Any]:
        charged = [i for i in self.intents.values() if i.status == "charged"]
        return {
            "intents": len(self.intents),
            "charged": len(charged),
            "charged_cents": sum(i.amount_cents for i in charged),
            "provider": getattr(self.provider, "name", None),
            "live_provider": getattr(self.provider, "name", None) not in (None, "mock"),
            "max_amount_cents": self.max_amount_cents,
            "currencies": sorted(self.allowed_currencies),
        }
