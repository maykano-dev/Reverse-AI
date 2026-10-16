"""Context-compaction tests.

Run: python3 -m unittest tests.test_context -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.context import compact_messages, transcript_chars  # noqa: E402
from reverseai.agent.providers.base import Message, Role  # noqa: E402


def _conv(n_tool: int, size: int) -> list[Message]:
    msgs = [Message(Role.SYSTEM, "system"), Message(Role.USER, "goal")]
    for i in range(n_tool):
        msgs.append(Message(Role.ASSISTANT, content=f"calling tool {i}"))
        msgs.append(Message(Role.TOOL, content="X" * size,
                            tool_call_id=f"c{i}", name="analyze_binary"))
    return msgs


class CompactTests(unittest.TestCase):
    def test_under_budget_unchanged(self):
        msgs = _conv(2, 100)
        self.assertIs(compact_messages(msgs, max_chars=10_000), msgs)

    def test_over_budget_shrinks(self):
        msgs = _conv(20, 5_000)  # ~100k chars
        before = transcript_chars(msgs)
        out = compact_messages(msgs, max_chars=20_000, keep_recent=4)
        after = transcript_chars(out)
        self.assertLess(after, before)

    def test_preserves_tool_call_ids(self):
        msgs = _conv(20, 5_000)
        out = compact_messages(msgs, max_chars=20_000, keep_recent=4)
        ids_before = [m.tool_call_id for m in msgs if m.role == Role.TOOL]
        ids_after = [m.tool_call_id for m in out if m.role == Role.TOOL]
        self.assertEqual(ids_before, ids_after)

    def test_recent_messages_kept_full(self):
        msgs = _conv(20, 5_000)
        out = compact_messages(msgs, max_chars=20_000, keep_recent=4)
        # the very last tool message must be intact (not stubbed)
        last_tool = [m for m in out if m.role == Role.TOOL][-1]
        self.assertNotIn("elided", last_tool.content)

    def test_count_unchanged(self):
        msgs = _conv(10, 5_000)
        out = compact_messages(msgs, max_chars=10_000)
        self.assertEqual(len(out), len(msgs))  # messages trimmed, never dropped


if __name__ == "__main__":
    unittest.main(verbosity=2)
