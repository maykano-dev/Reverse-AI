"""Tests for the MCP server that exposes ReverseAI's tools."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from reverseai.agent.tools import Permission
from reverseai.mcp.client import MCPClient, MCPError
from reverseai.mcp.server import MCPServer, server_tools
from reverseai.security.capabilities import CapabilityDenied, CapabilityPolicy

_ENABLED = {"REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES": "1", "REVERSEAI_ENABLE_MCP": "1"}


def _project(files):
    d = Path(tempfile.mkdtemp())
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, "utf-8")
    return d


class LoopbackTransport:
    """In-memory transport that drives a real MCPServer for round-trip tests."""

    def __init__(self, server):
        self.server = server
        self._reply = None

    def send(self, message):
        self._reply = self.server.handle(message)

    def receive(self, timeout=10.0):
        return self._reply

    def close(self):
        pass


class PermissionSurfaceTests(unittest.TestCase):
    def test_read_only_default_hides_write_and_execute(self):
        names = {t.name for t in server_tools(Permission.READ)}
        self.assertIn("search_code", names)
        self.assertIn("code_outline", names)
        self.assertIn("git_status", names)
        self.assertNotIn("write_file", names)
        self.assertNotIn("run_command", names)
        self.assertNotIn("git_commit", names)

    def test_write_permission_exposes_more(self):
        names = {t.name for t in server_tools(Permission.WRITE)}
        self.assertIn("write_file", names)
        self.assertIn("git_commit", names)
        self.assertIn("run_tests", names)


class ProtocolTests(unittest.TestCase):
    def test_initialize(self):
        srv = MCPServer(workspace=".")
        r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(r["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(r["result"]["serverInfo"]["name"], "reverseai")

    def test_tools_list(self):
        srv = MCPServer(workspace=".")
        r = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = r["result"]["tools"]
        self.assertTrue(any(t["name"] == "search_code" for t in tools))
        for t in tools:
            self.assertIn("inputSchema", t)
            self.assertTrue(t["description"])

    def test_notifications_get_no_reply(self):
        srv = MCPServer(workspace=".")
        self.assertIsNone(srv.handle({"method": "notifications/initialized"}))

    def test_unknown_method(self):
        srv = MCPServer(workspace=".")
        r = srv.handle({"jsonrpc": "2.0", "id": 9, "method": "frobnicate"})
        self.assertEqual(r["error"]["code"], -32601)

    def test_call_search_code(self):
        root = _project({"a.py": "def target():\n    return 1\n"})
        srv = MCPServer(workspace=root)
        r = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "search_code",
                                   "arguments": {"query": "def target"}}})
        res = r["result"]
        self.assertFalse(res["isError"])
        self.assertIn("a.py", res["content"][0]["text"])

    def test_call_unknown_tool_is_error(self):
        srv = MCPServer(workspace=".")
        r = srv.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": "nope", "arguments": {}}})
        self.assertTrue(r["result"]["isError"])

    def test_write_tool_not_exposed_at_read_permission(self):
        root = _project({"x.txt": "hi\n"})
        srv = MCPServer(workspace=root)  # read-only default
        r = srv.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                        "params": {"name": "write_file",
                                   "arguments": {"path": "y.txt", "content": "z"}}})
        self.assertTrue(r["result"]["isError"])
        self.assertIn("unexposed", r["result"]["content"][0]["text"])
        self.assertFalse((root / "y.txt").exists())


class GatingTests(unittest.TestCase):
    def test_serve_denied_without_capability(self):
        srv = MCPServer(workspace=".", policy=CapabilityPolicy(env={}))
        with self.assertRaises(CapabilityDenied):
            srv.require_capability()

    def test_serve_allowed_when_enabled(self):
        srv = MCPServer(workspace=".", policy=CapabilityPolicy(env=_ENABLED))
        srv.require_capability()  # should not raise


class ClientRoundTripTests(unittest.TestCase):
    def test_client_lists_and_calls(self):
        root = _project({"m.py": "def found_me():\n    pass\n"})
        server = MCPServer(workspace=root)
        policy = CapabilityPolicy(env=_ENABLED)
        client = MCPClient(LoopbackTransport(server), policy=policy)
        tools = client.list_tools()
        self.assertTrue(any(t["name"] == "code_outline" for t in tools))
        out = client.call_tool("search_code", {"query": "found_me"})
        self.assertFalse(out.get("isError"))
        self.assertIn("m.py", out["content"][0]["text"])

    def test_client_blocked_without_capability(self):
        server = MCPServer(workspace=".")
        client = MCPClient(LoopbackTransport(server), policy=CapabilityPolicy(env={}))
        with self.assertRaises(MCPError):
            client.list_tools()


if __name__ == "__main__":
    unittest.main()
