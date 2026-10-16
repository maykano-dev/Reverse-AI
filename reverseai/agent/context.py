"""Conversation context management for long investigations.

A multi-step run accumulates large tool outputs (hex dumps, disassembly, strings)
that can overflow the model's context window. This compacts the transcript by
truncating the *oldest* tool outputs first, keeping recent exchanges full and —
critically — preserving every tool_call_id linkage so the OpenAI/DeepSeek message
contract stays valid.
"""

from __future__ import annotations

from .providers.base import Message, Role

DEFAULT_MAX_CHARS = 300_000  # ~75k tokens, comfortably inside common windows
DEFAULT_KEEP_RECENT = 6
STUB_LEN = 240


def transcript_chars(messages: list[Message]) -> int:
    return sum(len(m.content or "") for m in messages)


def compact_messages(
    messages: list[Message],
    max_chars: int = DEFAULT_MAX_CHARS,
    keep_recent: int = DEFAULT_KEEP_RECENT,
    stub_len: int = STUB_LEN,
) -> list[Message]:
    """Return a transcript trimmed to fit ``max_chars`` when it is over budget.

    Only tool-result message *content* is truncated (oldest first, outside the
    recent window). Message structure, roles, and tool_call_id links are kept so
    the result is still a valid tool-calling conversation.
    """
    total = transcript_chars(messages)
    if total <= max_chars:
        return messages

    out = list(messages)
    n = len(out)
    cutoff = n - keep_recent
    for i in range(n):
        if total <= max_chars or i >= cutoff:
            break
        m = out[i]
        if m.role == Role.TOOL and m.content and len(m.content) > stub_len:
            elided = len(m.content) - stub_len
            new_content = (m.content[:stub_len]
                           + f"\n…[{elided} chars elided to fit context]")
            out[i] = Message(Role.TOOL, content=new_content,
                             tool_call_id=m.tool_call_id, name=m.name)
            total -= elided
    return out
