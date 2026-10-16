"""Structured logging with secret redaction.

A single defense against the most common operational leak: a credential landing
in a log line. The redacting formatter scrubs API-key-shaped tokens, bearer
tokens, and the live values of known secret environment variables before any
record is emitted. Level comes from REVERSEAI_LOG_LEVEL (default WARNING).
"""

from __future__ import annotations

import logging
import os
import re

_SECRET_ENV_VARS = ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")

_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"),             # OpenAI/DeepSeek-style keys
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.I),   # bearer tokens
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),                   # long hex secrets/tokens
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),               # GitHub tokens
]

_REDACTED = "«redacted»"


class Redactor:
    """Scrub secrets from arbitrary text."""

    def __init__(self, extra_values: list[str] | None = None) -> None:
        self._literals: list[str] = []
        for var in _SECRET_ENV_VARS:
            val = os.environ.get(var)
            if val and len(val) >= 6:
                self._literals.append(val)
        for v in extra_values or []:
            if v and len(v) >= 6:
                self._literals.append(v)

    def scrub(self, text: str) -> str:
        if not text:
            return text
        for literal in self._literals:
            if literal in text:
                text = text.replace(literal, _REDACTED)
        for pat in _PATTERNS:
            text = pat.sub(_REDACTED, text)
        return text


class _RedactingFormatter(logging.Formatter):
    def __init__(self, fmt: str) -> None:
        super().__init__(fmt)
        self._redactor = Redactor()

    def format(self, record: logging.LogRecord) -> str:
        return self._redactor.scrub(super().format(record))


_CONFIGURED: set[str] = set()


def get_logger(name: str = "reverseai") -> logging.Logger:
    logger = logging.getLogger(name)
    if name not in _CONFIGURED:
        level = os.environ.get("REVERSEAI_LOG_LEVEL", "WARNING").upper()
        handler = logging.StreamHandler()
        handler.setFormatter(_RedactingFormatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(getattr(logging, level, logging.WARNING))
        logger.propagate = False
        _CONFIGURED.add(name)
    return logger
