"""The last gate before an irreversible or out-of-sandbox action.

Future remote-control, payment, desktop, MCP, or hook features must call
``ActionGate.authorize`` before doing anything. The gate requires three things:

1. the feature is enabled in the capability policy;
2. a human issued a live, scoped approval token (except for explicitly
   configured read-only actions);
3. the decision is written to an append-only local audit log.

There is no ambient authority and no "remember this forever" switch. If any
piece is missing, the action is refused.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .approvals import Approval, ApprovalError, ApprovalLedger
from .capabilities import CapabilityDenied, CapabilityPolicy


class GateError(Exception):
    pass


@dataclass
class GateDecision:
    allowed: bool
    capability: str
    action: str
    scope: str
    reason: str
    approval_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActionGate:
    def __init__(self, policy: CapabilityPolicy | None = None,
                 ledger: ApprovalLedger | None = None,
                 audit_path: str | os.PathLike | None = None) -> None:
        self.policy = policy or CapabilityPolicy()
        self.ledger = ledger
        self.audit_path = Path(audit_path) if audit_path else None

    def _audit(self, decision: GateDecision) -> None:
        if self.audit_path is None:
            return
        row = {"at": time.time(), **decision.to_dict()}
        try:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
        except OSError:
            pass

    def authorize(self, capability: str, action: str, scope: str = "",
                  approval_token: str | None = None) -> GateDecision:
        decision = self.policy.decision(capability)
        if not decision.allowed:
            out = GateDecision(False, capability, action, scope, decision.reason)
            self._audit(out)
            raise CapabilityDenied(decision.reason)
        if approval_token:
            if self.ledger is None:
                out = GateDecision(False, capability, action, scope,
                                   "approval supplied but no ledger is configured")
                self._audit(out)
                raise GateError(out.reason)
            try:
                approval: Approval = self.ledger.consume(
                    approval_token, action, scope)
            except ApprovalError as exc:
                out = GateDecision(False, capability, action, scope, str(exc))
                self._audit(out)
                raise GateError(str(exc)) from exc
            out = GateDecision(True, capability, action, scope,
                               "capability enabled and approval consumed",
                               approval.id)
            self._audit(out)
            return out
        out = GateDecision(
            False, capability, action, scope,
            "this action requires a live, scoped approval token")
        self._audit(out)
        raise GateError(out.reason)
