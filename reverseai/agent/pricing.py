"""Approximate model pricing, used to show what a run cost.

Prices are USD per million tokens. They are intentionally easy to override:
set ``REVERSEAI_PRICE_<PROVIDER>_<MODEL>`` (dots and dashes become underscores)
to a pair ``input,output``. Unknown models report 0 rather than inventing a
number, and the UI labels estimates as estimates.
"""

from __future__ import annotations

import os
import re
from typing import Any

# (input, output) USD per 1M tokens. Update freely; this is not billing advice.
_PRICES: dict[str, tuple[float, float]] = {
    "deepseek/deepseek-chat": (0.27, 1.10),
    "deepseek/deepseek-reasoner": (0.55, 2.19),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.00),
    "anthropic/claude-sonnet-5": (3.00, 15.00),
    "anthropic/claude-sonnet-4-5": (3.00, 15.00),
    "ollama/": (0.0, 0.0),
}


def _key(provider: str, model: str) -> str:
    return f"{provider}/{model}".lower()


def price_for(provider: str, model: str) -> tuple[float, float] | None:
    key = _key(provider, model)
    raw = os.environ.get("REVERSEAI_PRICE_" + re.sub(r"[^A-Za-z0-9]", "_", key).upper())
    if raw:
        try:
            a, b = raw.split(",", 1)
            return float(a), float(b)
        except (ValueError, TypeError):
            pass
    if key in _PRICES:
        return _PRICES[key]
    for prefix, value in _PRICES.items():
        if prefix.endswith("/") and key.startswith(prefix):
            return value
    return None


def estimate_cost(provider: str, model: str, prompt_tokens: int,
                  completion_tokens: int) -> float | None:
    price = price_for(provider, model)
    if price is None:
        return None
    pin, pout = price
    return round((prompt_tokens / 1_000_000) * pin
                 + (completion_tokens / 1_000_000) * pout, 6)


def usage_row(provider: str, model: str, usage: dict[str, Any]) -> dict[str, Any]:
    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", 0) or 0)
    return {
        "provider": provider,
        "model": model,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": int(usage.get("total_tokens", prompt + completion) or 0),
        "cost_usd": estimate_cost(provider, model, prompt, completion),
    }
