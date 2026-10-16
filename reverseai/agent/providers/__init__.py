"""LLM providers for the ReverseAI agent."""

from .base import LLMProvider, LLMResponse, Message, Role, ToolCall, Usage
from .mock import MockProvider

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "Message",
    "Role",
    "ToolCall",
    "Usage",
    "MockProvider",
    "get_provider",
]


def get_provider(name: str = "deepseek", **kwargs):
    """Factory: construct a provider by name. Imports lazily so the mock path
    never requires provider-specific config."""
    name = name.lower()
    if name == "mock":
        return MockProvider(kwargs.get("script", []))
    if name == "deepseek":
        from .deepseek import DeepSeekProvider

        return DeepSeekProvider(**kwargs)
    raise ValueError(f"unknown provider: {name}")
