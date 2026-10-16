"""LLM provider abstraction.

The orchestrator talks to models only through this interface, so swapping
DeepSeek for a future in-house model (or Anthropic, or a local model) touches
nothing else. Message/tool-call shapes follow the widely-used OpenAI chat
convention, which DeepSeek is compatible with.
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    @classmethod
    def from_openai(cls, raw: dict[str, Any]) -> "ToolCall":
        fn = raw.get("function", {})
        raw_args = fn.get("arguments", "{}")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except (json.JSONDecodeError, TypeError):
            args = {"__raw__": raw_args}
        return cls(id=raw.get("id", ""), name=fn.get("name", ""), arguments=args)


@dataclass
class Message:
    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None   # for role == TOOL
    name: str | None = None           # tool name, for role == TOOL

    def to_openai(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role.value}
        if self.content is not None:
            msg["content"] = self.content
        elif self.role != Role.ASSISTANT:
            msg["content"] = ""
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in self.tool_calls
            ]
        if self.role == Role.TOOL:
            msg["tool_call_id"] = self.tool_call_id or ""
            if self.name:
                msg["name"] = self.name
        return msg


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    usage: Usage = field(default_factory=Usage)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(abc.ABC):
    name: str = "base"
    model: str = ""

    @abc.abstractmethod
    def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        ...
