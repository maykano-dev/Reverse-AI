"""Model-call resilience: retries and provider fallback."""

import os
import unittest

from reverseai.agent.conversation import _resilient_chat
from reverseai.agent.providers.base import LLMResponse


class _Prov:
    def __init__(self, name, fail_times=0, boom=False):
        self.name = name
        self.fail_times = fail_times
        self.boom = boom
        self.calls = 0

    def chat(self, messages, tools=None, temperature=0, max_tokens=0):
        self.calls += 1
        if self.boom or self.calls <= self.fail_times:
            raise RuntimeError(f"{self.name} transient fail")
        return LLMResponse(content="ok from " + self.name, tool_calls=[])


class _Agent:
    def __init__(self, prov):
        self.provider = prov
        self.temperature = 0
        self.max_tokens = 64


class ResilienceTests(unittest.TestCase):
    def setUp(self):
        os.environ["REVERSEAI_MODEL_RETRIES"] = "2"
        os.environ.pop("REVERSEAI_FALLBACK_PROVIDERS", None)

    def test_retries_then_succeeds(self):
        p = _Prov("primary", fail_times=2)
        resp, used = _resilient_chat(_Agent(p), [], [], lambda e: None)
        self.assertEqual(resp.content, "ok from primary")
        self.assertEqual(p.calls, 3)          # 1 + 2 retries
        self.assertEqual(used.name, "primary")

    def test_falls_back_to_backup(self):
        import reverseai.agent as agmod
        backup = _Prov("backup")
        orig = agmod.get_provider
        agmod.get_provider = lambda n: backup if n == "backup" else orig(n)
        os.environ["REVERSEAI_FALLBACK_PROVIDERS"] = "backup"
        try:
            p = _Prov("primary", boom=True)
            resp, used = _resilient_chat(_Agent(p), [], [], lambda e: None)
        finally:
            agmod.get_provider = orig
        self.assertEqual(used.name, "backup")
        self.assertEqual(resp.content, "ok from backup")

    def test_all_fail_raises(self):
        p = _Prov("primary", boom=True)
        with self.assertRaises(Exception):
            _resilient_chat(_Agent(p), [], [], lambda e: None)


if __name__ == "__main__":
    unittest.main()
