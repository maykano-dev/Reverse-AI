"""MCP protocol and signed sandboxed hooks."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.hooks.runner import (  # noqa: E402
    HookError, HookManifest, HookRegistry, HookRunner, sign_manifest,
)
from reverseai.mcp.client import (  # noqa: E402
    FakeMCPTransport, MCPClient, MCPError, MCPManifest, MCPRegistry,
)
from reverseai.sandbox import SandboxPolicy, create_sandbox  # noqa: E402
from reverseai.security.capabilities import CapabilityPolicy  # noqa: E402

MCP_ENV = {
    "REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES": "1",
    "REVERSEAI_ENABLE_MCP": "1",
}
HOOK_ENV = {
    "REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES": "1",
    "REVERSEAI_ENABLE_HOOKS": "1",
    "REVERSEAI_HOOK_KEY": "h" * 32,
}


def _sandbox_ok() -> bool:
    try:
        create_sandbox(SandboxPolicy(allow_untrusted_execution=True))
        return True
    except Exception:
        return False


SANDBOX = _sandbox_ok()


class MCPTests(unittest.TestCase):
    def transport(self):
        return FakeMCPTransport(
            tools=[{"name": "echo", "description": "echo"},
                   {"name": "other", "description": "blocked"}],
            replies={"echo": [{"type": "text", "text": "hello"}]})

    def test_client_protocol_and_allowlist(self):
        client = MCPClient(self.transport(), allowed_tools=["echo"],
                           policy=CapabilityPolicy(MCP_ENV))
        self.assertIn("protocolVersion", client.initialize())
        tools = client.list_tools()
        self.assertEqual([t["name"] for t in tools], ["echo"])
        out = client.call_tool("echo", {"x": 1})
        self.assertEqual(out["content"][0]["text"], "hello")
        with self.assertRaises(MCPError):
            client.call_tool("other", {})

    def test_capability_denied(self):
        client = MCPClient(self.transport(), allowed_tools=["echo"],
                           policy=CapabilityPolicy({}))
        with self.assertRaises(MCPError):
            client.initialize()

    def test_manifest_validation_and_registry(self):
        good = MCPManifest("files", ["python", "server.py"],
                           allowed_tools=["read"])
        self.assertEqual(good.validate(), [])
        bad = MCPManifest("bad", ["sh", "-c", "rm -rf /"])
        self.assertTrue(bad.validate())
        reg = MCPRegistry()
        reg.add(good)
        self.assertEqual(len(reg.list()), 1)

    def test_host_transport_requires_explicit_allow(self):
        from reverseai.mcp.client import StdioTransport

        with self.assertRaises(MCPError):
            StdioTransport([sys.executable, "-c", "print()"])


@unittest.skipUnless(SANDBOX, "isolating sandbox unavailable")
class HookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["REVERSEAI_HOOK_KEY"] = "h" * 32
        self.runner = HookRunner(policy=CapabilityPolicy(HOOK_ENV),
                                 audit_path=Path(self.tmp.name) / "audit.jsonl")

    def tearDown(self):
        os.environ.pop("REVERSEAI_HOOK_KEY", None)
        self.tmp.cleanup()

    def manifest(self):
        code = ("import json,sys; p=json.load(sys.stdin); "
                "print(json.dumps({'seen': p.get('x')}))")
        m = HookManifest("echo", "tool.before",
                         [sys.executable, "-c", code],
                         timeout_seconds=5)
        m.signature = sign_manifest(m.to_dict())
        return m

    def test_signed_hook_runs_in_sandbox(self):
        m = self.manifest()
        result = self.runner.run(m, {"x": 7})
        self.assertTrue(result.ok, result.stderr)
        self.assertEqual(json.loads(result.stdout)["seen"], 7)
        self.assertIn("bubblewrap", result.isolation.get("backend", ""))

    def test_unsigned_manifest_is_refused(self):
        reg = HookRegistry(Path(self.tmp.name) / "hooks.json")
        m = HookManifest("unsigned", "tool.before", ["true"])
        with self.assertRaises(HookError):
            reg.add(m)

    def test_capability_denied(self):
        runner = HookRunner(policy=CapabilityPolicy({}))
        result = runner.run(self.manifest(), {})
        self.assertFalse(result.ok)
        self.assertIn("disabled", result.error)

    def test_invalid_event_is_refused(self):
        m = HookManifest("x", "not.an.event", ["true"])
        self.assertTrue(m.validate())


if __name__ == "__main__":
    unittest.main(verbosity=2)
