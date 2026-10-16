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


class AnthropicTests(unittest.TestCase):
    def test_message_translation(self):
        from reverseai.agent.providers.anthropic import AnthropicProvider
        from reverseai.agent.providers.base import ToolCall

        msgs = [
            Message(Role.SYSTEM, "be good"),
            Message(Role.USER, "analyze it"),
            Message(Role.ASSISTANT, content=None,
                    tool_calls=[ToolCall("t1", "analyze_binary", {})]),
            Message(Role.TOOL, content="format: elf", tool_call_id="t1",
                    name="analyze_binary"),
        ]
        system, converted = AnthropicProvider._to_anthropic(msgs)
        self.assertEqual(system, "be good")
        # assistant tool_use block present
        self.assertEqual(converted[1]["content"][0]["type"], "tool_use")
        # tool result mapped to a user turn with tool_result block
        self.assertEqual(converted[2]["content"][0]["type"], "tool_result")
        self.assertEqual(converted[2]["content"][0]["tool_use_id"], "t1")

    def test_parse_tool_use(self):
        from reverseai.agent.providers.anthropic import AnthropicProvider

        data = {
            "content": [
                {"type": "text", "text": "let me check"},
                {"type": "tool_use", "id": "u1", "name": "read_bytes",
                 "input": {"offset": 0, "length": 16}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        resp = AnthropicProvider._parse(data)
        self.assertTrue(resp.wants_tools)
        self.assertEqual(resp.tool_calls[0].name, "read_bytes")
        self.assertEqual(resp.tool_calls[0].arguments["length"], 16)
        self.assertEqual(resp.usage.total_tokens, 15)

    def test_tool_spec_conversion(self):
        from reverseai.agent.providers.anthropic import AnthropicProvider

        spec = {"type": "function", "function": {
            "name": "x", "description": "d", "parameters": {"type": "object"}}}
        a = AnthropicProvider._tool_to_anthropic(spec)
        self.assertEqual(a["name"], "x")
        self.assertIn("input_schema", a)


class MessageTests(unittest.TestCase):
    def test_assistant_with_tool_calls_serializes(self):
        from reverseai.agent.providers.base import ToolCall

        m = Message(Role.ASSISTANT, content=None,
                    tool_calls=[ToolCall("c1", "t", {"a": 1})])
        d = m.to_openai()
        self.assertEqual(d["tool_calls"][0]["function"]["name"], "t")


if __name__ == "__main__":
    unittest.main(verbosity=2)
