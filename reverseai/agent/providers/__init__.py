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
    if name in ("openai", "openai-compatible"):
        from .openai_compat import OpenAICompatibleProvider

        kwargs.setdefault("api_key_env", "OPENAI_API_KEY")
        kwargs.setdefault("base_url", "https://api.openai.com/v1")
        kwargs.setdefault("model", "gpt-4o-mini")
        return OpenAICompatibleProvider(**kwargs)
    if name in ("anthropic", "claude"):
        from .anthropic import AnthropicProvider

        return AnthropicProvider(**kwargs)
    if name == "ollama":
        # Local models via Ollama's OpenAI-compatible endpoint (no key needed).
        import os

        from .openai_compat import OpenAICompatibleProvider

        kwargs.setdefault("base_url", os.environ.get(
            "OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"))
        kwargs.setdefault("model", os.environ.get("OLLAMA_MODEL", "llama3.2"))
        kwargs.setdefault("api_key", "ollama")
        return OpenAICompatibleProvider(**kwargs)
    raise ValueError(f"unknown provider: {name}")
