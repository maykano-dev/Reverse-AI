"""DeepSeek provider (OpenAI-compatible Chat Completions).

Uses only the standard library (urllib) so the platform has no hard dependency
on a vendor SDK. Reads the API key from the environment; never logs it.

Env:
  DEEPSEEK_API_KEY   required
  DEEPSEEK_BASE_URL  optional, defaults to https://api.deepseek.com
  DEEPSEEK_MODEL     optional, defaults to deepseek-chat

Models: "deepseek-chat" (general) and "deepseek-reasoner" (reasoning). Both
speak the OpenAI function-calling format this provider emits.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .base import LLMProvider, LLMResponse, Message, ToolCall, Usage

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class ProviderError(Exception):
    pass


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise ProviderError(
                "DEEPSEEK_API_KEY is not set. Export it or pass api_key=..."
            )
        self.model = model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    def chat(self, messages, tools=None, temperature=0.0, max_tokens=4096) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = self._post("/chat/completions", payload)
        return self._parse(data)

    # --- HTTP ---

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:500]
                # Retry transient server/rate errors; fail fast on 4xx auth/bad-request.
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_retries - 1:
                    last_err = ProviderError(f"HTTP {exc.code}: {detail}")
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ProviderError(f"DeepSeek HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_err = exc
                if attempt < self.max_retries - 1:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ProviderError(f"DeepSeek request failed: {exc}") from exc
        raise ProviderError(f"DeepSeek request failed after retries: {last_err}")

    # --- parsing ---

    @staticmethod
    def _parse(data: dict[str, Any]) -> LLMResponse:
        choices = data.get("choices") or [{}]
        choice = choices[0]
        msg = choice.get("message", {}) or {}
        tool_calls = [ToolCall.from_openai(tc) for tc in (msg.get("tool_calls") or [])]
        usage_raw = data.get("usage", {}) or {}
        usage = Usage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )
        return LLMResponse(
            content=msg.get("content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", ""),
            usage=usage,
            raw=data,
        )
