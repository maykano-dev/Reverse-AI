"""Generic OpenAI-compatible Chat Completions provider (stdlib only).

Works with any endpoint speaking the OpenAI chat + function-calling format:
DeepSeek, OpenAI, Together, Groq, a local vLLM/llama.cpp server, or a future
in-house model fronted by an OpenAI-compatible gateway. The DeepSeek provider is
a thin preset over this. Swapping the model behind ReverseAI is a config change,
not a code change.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .base import LLMProvider, LLMResponse, Message, ToolCall, Usage


class ProviderError(Exception):
    pass


class OpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        api_key_env: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        key = api_key or (os.environ.get(api_key_env, "") if api_key_env else "")
        if not key:
            raise ProviderError(
                f"API key not set (pass api_key or set {api_key_env or 'the key env var'})")
        self.api_key = key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

    def chat(self, messages, tools=None, temperature=0.0, max_tokens=8192) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return self._parse(self._post("/chat/completions", payload))

    def chat_stream(self, messages, tools=None, temperature=0.0, max_tokens=8192):
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        content: list[str] = []
        tool_acc: dict[int, dict] = {}
        finish, usage = "", Usage()
        for obj in self._post_stream("/chat/completions", payload):
            u = obj.get("usage") or {}
            if u:
                usage = Usage(prompt_tokens=u.get("prompt_tokens", 0),
                              completion_tokens=u.get("completion_tokens", 0),
                              total_tokens=u.get("total_tokens", 0))
            for choice in obj.get("choices") or []:
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                delta = choice.get("delta") or {}
                c = delta.get("content")
                if c:
                    content.append(c)
                    yield c
                for tc in delta.get("tool_calls") or []:
                    acc = tool_acc.setdefault(tc.get("index", 0),
                                              {"id": "", "name": "", "args": ""})
                    if tc.get("id"):
                        acc["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        acc["name"] += fn["name"]
                    if fn.get("arguments"):
                        acc["args"] += fn["arguments"]
        tool_calls = [
            ToolCall.from_openai({"id": a["id"] or f"call_{i}",
                                  "function": {"name": a["name"], "arguments": a["args"] or "{}"}})
            for i, a in sorted(tool_acc.items())]
        return LLMResponse(content="".join(content) or None, tool_calls=tool_calls,
                           finish_reason=finish, usage=usage, raw={})

    def _post_stream(self, path: str, payload: dict[str, Any]):
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "text/event-stream",
        }
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError:
                        continue
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ProviderError(f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ProviderError(f"stream failed: {exc}") from exc

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
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_retries - 1:
                    last_err = ProviderError(f"HTTP {exc.code}: {detail}")
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ProviderError(f"HTTP {exc.code}: {detail}") from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last_err = exc
                if attempt < self.max_retries - 1:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise ProviderError(f"request failed: {exc}") from exc
        raise ProviderError(f"request failed after retries: {last_err}")

    @staticmethod
    def _parse(data: dict[str, Any]) -> LLMResponse:
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message", {}) or {}
        tool_calls = [ToolCall.from_openai(tc) for tc in (msg.get("tool_calls") or [])]
        u = data.get("usage", {}) or {}
        return LLMResponse(
            content=msg.get("content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", ""),
            usage=Usage(
                prompt_tokens=u.get("prompt_tokens", 0),
                completion_tokens=u.get("completion_tokens", 0),
                total_tokens=u.get("total_tokens", 0),
            ),
            raw=data,
        )
