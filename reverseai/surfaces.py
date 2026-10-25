"""Inventory the dangerous surfaces without enabling them.

This is the operator's map: what exists, what is configured, and what is still
absent. It never returns tokens or secret values.
"""

from __future__ import annotations

import os
from typing import Any

from .mcp.client import MCPManifest
from .sandbox.cgroup import detect as cgroup_detect
from .sandbox.landlock import abi_version as landlock_abi
from .sandbox.readiness import assess_execution
from .security.capabilities import CapabilityPolicy


def surface_status(env: dict[str, str] | None = None,
                   target: str | None = None) -> dict[str, Any]:
    e = env if env is not None else os.environ
    policy = CapabilityPolicy(e).status()
    telegram_token = str(e.get("REVERSEAI_TELEGRAM_TOKEN", "") or "")
    telegram_chats = str(e.get("REVERSEAI_TELEGRAM_CHATS", "") or "")
    hook_key = bool(str(e.get("REVERSEAI_HOOK_KEY", "") or "").strip())
    from .sandbox.backends.qemu_backend import QemuVmBackend

    out: dict[str, Any] = {
        "capabilities": policy,
        "desktop": {
            "enabled": policy["desktop_workstation"]["allowed"],
            "listener": "loopback-only; bearer token; no input backend",
            "input_injection": False,
        },
        "telegram": {
            "enabled": policy["remote_control"]["allowed"],
            "token_configured": bool(telegram_token),
            "allowed_chat_count": len([x for x in telegram_chats.split(",") if x.strip()]),
            "commands": ["/status", "/jobs", "/readiness", "/discover", "/pair"],
        },
        "payments": {
            "enabled": policy["payments"]["allowed"],
            "bundled_provider": "mock",
            "http_provider": "operator-supplied endpoint only",
            "live_provider": False,
            "card_data": "not accepted",
        },
        "mcp": {
            "enabled": policy["mcp"]["allowed"],
            "host_transport": "explicit allow_host=True required",
            "manifest": MCPManifest("demo", ["server"]).validate() == [],
        },
        "hooks": {
            "enabled": policy["hooks"]["allowed"],
            "signing_key_configured": hook_key,
            "runner": "sandboxed subprocess",
        },
        "self_training": {
            "enabled": policy["self_training"]["allowed"],
            "dataset": "verified traces only",
            "auto_train": False,
            "deploy": "separate approval",
        },
        "deployment": {
            "enabled": policy["deployment"]["allowed"],
            "auto_deploy": False,
            "transport": "injected by operator",
            "rollback": "explicit approval required",
        },
        "qemu": QemuVmBackend.preflight(),
        "landlock": {"abi": landlock_abi(),
                     "enforcement": "not applied; bubblewrap is the boundary"},
        "cgroup": cgroup_detect(),
        "note": ("This inventory is not a permission grant. Each surface still "
                 "requires its capability opt-in and, for irreversible actions, "
                 "a live approval."),
    }
    if target:
        try:
            out["readiness"] = assess_execution(target).to_dict()
        except Exception as exc:
            out["readiness"] = {"error": str(exc)}
    return out
