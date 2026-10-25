"""Deny-by-default policy for high-risk capabilities.

Some product ideas are deliberately not implemented yet: remote control, a
credential vault, payments, live desktop workstations, persistent squads, MCP
connectors, and hooks. They need a separate threat model, a clear data boundary,
and an operator who explicitly accepts the risk.

This module is the gate those features must pass through. It denies everything by
default, requires both a global opt-in and a per-capability opt-in, and requires
an encryption key for anything that stores secrets. A future implementation must
call ``require()`` before touching the host, the network, or stored credentials.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


class CapabilityDenied(RuntimeError):
    pass


@dataclass(frozen=True)
class Capability:
    name: str
    risk: str
    reason: str
    env: str
    needs_secret: str | None = None


CAPABILITIES: dict[str, Capability] = {
    "remote_control": Capability(
        "remote_control", "critical",
        "Remote command channels can turn a local agent into a network service.",
        "REVERSEAI_ENABLE_REMOTE_CONTROL"),
    "credential_vault": Capability(
        "credential_vault", "critical",
        "A vault stores credentials and must use an audited encryption boundary.",
        "REVERSEAI_ENABLE_CREDENTIAL_VAULT", "REVERSEAI_VAULT_KEY"),
    "payments": Capability(
        "payments", "critical",
        "Payments are irreversible and require explicit human approval.",
        "REVERSEAI_ENABLE_PAYMENTS", "REVERSEAI_VAULT_KEY"),
    "desktop_workstation": Capability(
        "desktop_workstation", "high",
        "A live desktop expands the attack surface from a sandbox to a VM/browser.",
        "REVERSEAI_ENABLE_WORKSTATION"),
    "persistent_squads": Capability(
        "persistent_squads", "high",
        "Persistent multi-agent authority needs per-agent isolation and budgets.",
        "REVERSEAI_ENABLE_SQUADS"),
    "mcp": Capability(
        "mcp", "high",
        "MCP servers are third-party code and data with their own permissions.",
        "REVERSEAI_ENABLE_MCP"),
    "hooks": Capability(
        "hooks", "high",
        "Hooks run operator code around tool calls and can bypass the mediator.",
        "REVERSEAI_ENABLE_HOOKS"),
}

_MASTER_ENV = "REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES"


@dataclass
class CapabilityDecision:
    name: str
    allowed: bool
    reason: str
    risk: str = ""
    env: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapabilityPolicy:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        self._env = dict(os.environ if env is None else env)

    def _get(self, key: str) -> str:
        return str(self._env.get(key, "")).strip()

    def decision(self, name: str) -> CapabilityDecision:
        cap = CAPABILITIES.get(name)
        if cap is None:
            return CapabilityDecision(name, False, "unknown capability", "unknown", "")
        if self._get(_MASTER_ENV) != "1":
            return CapabilityDecision(
                name, False,
                f"{name} is disabled. Set {_MASTER_ENV}=1 and {cap.env}=1 only "
                "after reviewing docs/SECURITY.md.", cap.risk, cap.env)
        if self._get(cap.env) != "1":
            return CapabilityDecision(
                name, False,
                f"{name} is disabled. Enable it explicitly with {cap.env}=1.",
                cap.risk, cap.env)
        if cap.needs_secret and not self._get(cap.needs_secret):
            return CapabilityDecision(
                name, False,
                f"{name} needs {cap.needs_secret}; refusing to start without it.",
                cap.risk, cap.env)
        return CapabilityDecision(
            name, True,
            f"{name} is explicitly enabled by the operator.", cap.risk, cap.env)

    def allowed(self, name: str) -> bool:
        return self.decision(name).allowed

    def require(self, name: str) -> None:
        decision = self.decision(name)
        if not decision.allowed:
            raise CapabilityDenied(decision.reason)

    def status(self) -> dict[str, dict[str, Any]]:
        return {name: self.decision(name).to_dict()
                for name in sorted(CAPABILITIES)}
