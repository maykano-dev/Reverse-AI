"""Deterministic scripted provider for offline development and tests.

Drive the full agent loop with no network and no API key. A script is a list of
LLMResponse objects (or a callable that inspects the conversation and returns
one), consumed in order.
"""

from __future__ import annotations

from typing import Any, Callable

from .base import LLMProvider, LLMResponse, Message, ToolCall

ScriptStep = LLMResponse | Callable[[list[Message]], LLMResponse]


class MockProvider(LLMProvider):
    name = "mock"
    model = "mock-1"

    def __init__(self, script: list[ScriptStep]) -> None:
        self._script = list(script)
        self._i = 0
        self.calls: list[list[Message]] = []

    def chat(self, messages, tools=None, temperature=0.0, max_tokens=8192) -> LLMResponse:
        self.calls.append(list(messages))
        if self._i >= len(self._script):
            return LLMResponse(content="(mock script exhausted)", finish_reason="stop")
        step = self._script[self._i]
        self._i += 1
        return step(messages) if callable(step) else step


def say(text: str) -> LLMResponse:
    return LLMResponse(content=text, finish_reason="stop")


def call(tool: str, arguments: dict[str, Any], call_id: str = "call_1") -> LLMResponse:
    return LLMResponse(
        tool_calls=[ToolCall(id=call_id, name=tool, arguments=arguments)],
        finish_reason="tool_calls",
    )
