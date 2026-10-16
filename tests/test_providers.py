"""Provider-layer tests — parsing and factory, no network.

Run: python3 -m unittest tests.test_providers -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.providers import get_provider  # noqa: E402
from reverseai.agent.providers.base import Message, Role  # noqa: E402
from reverseai.agent.providers.openai_compat import (  # noqa: E402
    OpenAICompatibleProvider,
    ProviderError,
)


class ParseTests(unittest.TestCase):
    def test_parse_text_response(self):
        data = {
            "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        }
        resp = OpenAICompatibleProvider._parse(data)
        self.assertEqual(resp.content, "hello")
        self.assertFalse(resp.wants_tools)
        self.assertEqual(resp.usage.total_tokens, 4)

    def test_parse_tool_call(self):
        data = {"choices": [{"message": {"content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "analyze_binary", "arguments": "{\"x\": 1}"}}]},
            "finish_reason": "tool_calls"}]}
        resp = OpenAICompatibleProvider._parse(data)
        self.assertTrue(resp.wants_tools)
        self.assertEqual(resp.tool_calls[0].name, "analyze_binary")
        self.assertEqual(resp.tool_calls[0].arguments, {"x": 1})

    def test_parse_malformed_tool_args(self):
        data = {"choices": [{"message": {"tool_calls": [
            {"id": "c", "function": {"name": "t", "arguments": "not json"}}]}}]}
        resp = OpenAICompatibleProvider._parse(data)
        self.assertIn("__raw__", resp.tool_calls[0].arguments)


class FactoryTests(unittest.TestCase):
    def test_unknown_provider(self):
        with self.assertRaises(ValueError):
            get_provider("nonexistent")

    def test_deepseek_requires_key(self):
        import os

        if os.environ.get("DEEPSEEK_API_KEY"):
            self.skipTest("key present")
        with self.assertRaises(ProviderError):
            get_provider("deepseek")

    def test_explicit_key_constructs(self):
        p = get_provider("openai", api_key="test-key-123456", base_url="http://x", model="m")
        self.assertIsInstance(p, OpenAICompatibleProvider)
        self.assertEqual(p.model, "m")


class MessageTests(unittest.TestCase):
    def test_assistant_with_tool_calls_serializes(self):
        from reverseai.agent.providers.base import ToolCall

        m = Message(Role.ASSISTANT, content=None,
                    tool_calls=[ToolCall("c1", "t", {"a": 1})])
        d = m.to_openai()
        self.assertEqual(d["tool_calls"][0]["function"]["name"], "t")


if __name__ == "__main__":
    unittest.main(verbosity=2)
