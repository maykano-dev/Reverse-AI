"""Anthropic (Claude) provider — native Messages API (stdlib only).

An alternative to the OpenAI-compatible path. Claude's Messages API differs:
the system prompt is a top-level field, tool calls arrive as `tool_use` content
blocks, and tool results are sent back as `tool_result` blocks in a user turn.
This provider translates ReverseAI's uniform Message list to and from that shape,
so the agent loop is unchanged.

Env:
  ANTHROPIC_API_KEY   required
  ANTHROPIC_MODEL     optional, defaults to claude-sonnet-5
  ANTHROPIC_BASE_URL  optional, defaults to https://api.anthropic.com
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .base import LLMProvider, LLMResponse, Message, Role, ToolCall, Usage
from .openai_compat import ProviderError

DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_MODEL = "claude-sonnet-5"
API_VERSION = "2023-06-01"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 base_url: str | None = None, timeout: float = 120.0,
                 max_retries: int = 3) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get("ANTHROPIC_BASE_URL",
                                                    DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    def chat(self, messages, tools=None, temperature=0.0, max_tokens=4096) -> LLMResponse:
        system, converted = self._to_anthropic(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": converted,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [self._tool_to_anthropic(t) for t in tools]
        return self._parse(self._post("/v1/messages", payload))

    # --- translation ---

    @staticmethod
    def _tool_to_anthropic(spec: dict[str, Any]) -> dict[str, Any]:
        fn = spec.get("function", spec)
        return {
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        }

    @staticmethod
    def _to_anthropic(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        out: list[dict[str, Any]] = []
        for m in messages:
            if m.role == Role.SYSTEM:
                if m.content:
                    system_parts.append(m.content)
            elif m.role == Role.USER:
                out.append({"role": "user", "content": m.content or ""})
            elif m.role == Role.ASSISTANT:
                blocks: list[dict[str, Any]] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    blocks.append({"type": "tool_use", "id": tc.id,
                                   "name": tc.name, "input": tc.arguments})
                out.append({"role": "assistant", "content": blocks or ""})
            elif m.role == Role.TOOL:
                out.append({"role": "user", "content": [{
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id or "",
                    "content": m.content or "",
                }]})
        return "\n\n".join(system_parts), out

    @staticmethod
    def _parse(data: dict[str, Any]) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in data.get("content", []) or []:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", ""), name=block.get("name", ""),
                    arguments=block.get("input", {}) or {}))
        u = data.get("usage", {}) or {}
        return LLMResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            finish_reason=data.get("stop_reason", ""),
            usage=Usage(prompt_tokens=u.get("input_tokens", 0),
                        completion_tokens=u.get("output_tokens", 0),
                        total_tokens=u.get("input_tokens", 0) + u.get("output_tokens", 0)),
            raw=data,
        )

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
        }
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:500]
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_retries - 1:
                    last_err = ProviderError(f"HTTP {exc.code}: {detail}")
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ProviderError(f"Anthropic HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_err = exc
                if attempt < self.max_retries - 1:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ProviderError(f"Anthropic request failed: {exc}") from exc
        raise ProviderError(f"Anthropic request failed after retries: {last_err}")
