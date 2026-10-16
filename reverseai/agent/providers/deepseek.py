"""DeepSeek provider — a preset of the generic OpenAI-compatible client.

Env:
  DEEPSEEK_API_KEY   required
  DEEPSEEK_BASE_URL  optional, defaults to https://api.deepseek.com
  DEEPSEEK_MODEL     optional, defaults to deepseek-chat

Models: "deepseek-chat" (general) and "deepseek-reasoner" (reasoning).
"""

from __future__ import annotations

import os

from .openai_compat import OpenAICompatibleProvider, ProviderError

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

__all__ = ["DeepSeekProvider", "ProviderError"]


class DeepSeekProvider(OpenAICompatibleProvider):
    name = "deepseek"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(
            base_url=base_url or os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
            model=model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL),
            api_key=api_key,
            api_key_env="DEEPSEEK_API_KEY",
            timeout=timeout,
            max_retries=max_retries,
        )
