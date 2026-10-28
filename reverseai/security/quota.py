"""Optional per-token quotas for the HTTP API.

The server remains single-token by default. This module adds an explicit monthly
run/token/cost ceiling per bearer token so a public deployment can refuse abuse
without pretending to provide full multi-tenant isolation.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class QuotaPolicy:
    runs_per_month: int = 0        # 0 = unlimited
    tokens_per_month: int = 0
    cost_usd_per_month: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_env(cls, prefix: str = "REVERSEAI_QUOTA_") -> "QuotaPolicy":
        def _num(name: str, cast, default):
            try:
                return cast(os.environ.get(prefix + name, default) or default)
            except (TypeError, ValueError):
                return default
        return cls(
            runs_per_month=_num("RUNS_PER_MONTH", int, 0),
            tokens_per_month=_num("TOKENS_PER_MONTH", int, 0),
            cost_usd_per_month=_num("COST_USD_PER_MONTH", float, 0.0),
        )

    def enabled(self) -> bool:
        return bool(self.runs_per_month or self.tokens_per_month
                    or self.cost_usd_per_month)


@dataclass
class QuotaUsage:
    month: str
    runs: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    last_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class QuotaError(Exception):
    pass


def _month() -> str:
    return time.strftime("%Y-%m")


def token_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:16]


class QuotaTracker:
    def __init__(self, path: str | os.PathLike | None = None,
                 policy: QuotaPolicy | None = None) -> None:
        self.path = Path(path or Path.home() / ".reverseai" / "quotas.json")
        self.policy = policy or QuotaPolicy()
        self.tokens: dict[str, QuotaUsage] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for tid, row in (data.get("tokens") or {}).items():
            try:
                self.tokens[tid] = QuotaUsage(**row)
            except (TypeError, ValueError):
                continue

    def _save(self) -> None:
        import tempfile

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".quota-", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"version": 1, "tokens": {
                    k: v.to_dict() for k, v in self.tokens.items()}}, fh, indent=2)
            os.replace(tmp, self.path)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def _usage(self, token: str) -> QuotaUsage:
        tid = token_id(token)
        current = _month()
        usage = self.tokens.get(tid)
        if usage is None or usage.month != current:
            usage = QuotaUsage(current)
            self.tokens[tid] = usage
        return usage

    def check(self, token: str, *, runs: int = 1, tokens: int = 0,
              cost_usd: float = 0.0) -> dict[str, Any]:
        with self._lock:
            usage = self._usage(token)
            p = self.policy
            problems = []
            if p.runs_per_month and usage.runs + runs > p.runs_per_month:
                problems.append("monthly run quota exceeded")
            if p.tokens_per_month and usage.tokens + tokens > p.tokens_per_month:
                problems.append("monthly token quota exceeded")
            if p.cost_usd_per_month and usage.cost_usd + cost_usd > p.cost_usd_per_month:
                problems.append("monthly cost quota exceeded")
            return {
                "allowed": not problems, "problems": problems,
                "usage": usage.to_dict(), "policy": p.to_dict(),
            }

    def consume(self, token: str, *, runs: int = 1, tokens: int = 0,
                cost_usd: float = 0.0) -> dict[str, Any]:
        with self._lock:
            check = self.check(token, runs=runs, tokens=tokens, cost_usd=cost_usd)
            if not check["allowed"]:
                raise QuotaError("; ".join(check["problems"]))
            usage = self._usage(token)
            usage.runs += max(0, int(runs))
            usage.tokens += max(0, int(tokens))
            usage.cost_usd = round(usage.cost_usd + max(0.0, float(cost_usd)), 6)
            usage.last_at = time.time()
            self._save()
            return {"allowed": True, "usage": usage.to_dict()}
