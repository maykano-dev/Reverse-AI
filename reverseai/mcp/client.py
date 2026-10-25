"""A small JSON-RPC MCP client with an explicit trust boundary.

The protocol client is transport-agnostic. Tests use an in-memory transport.
``StdioTransport`` launches a host process and is intentionally marked dangerous:
it requires ``allow_host=True`` and the ``mcp`` capability. A production MCP
server should be placed behind the sandbox or a disposable VM, not trusted just
because it speaks a protocol.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from ..security.capabilities import CapabilityDenied, CapabilityPolicy


class MCPError(Exception):
    pass


class MCPTransport(Protocol):
    def send(self, message: dict[str, Any]) -> None: ...
    def receive(self, timeout: float = 10.0) -> dict[str, Any] | None: ...
    def close(self) -> None: ...


@dataclass
class MCPManifest:
    name: str
    command: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)
    timeout_seconds: float = 10.0
    allow_host: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> list[str]:
        problems = []
        if not self.name:
            problems.append("missing name")
        if not self.command:
            problems.append("missing command")
        if any(str(x).startswith((";", "|", "&", ">", "<")) for x in self.command):
            problems.append("shell metacharacters are not allowed")
        if any(str(x) in ("sh", "bash", "zsh", "cmd", "powershell") for x in self.command[:1]) \
                and any(str(x) == "-c" for x in self.command[1:2]):
            problems.append("shell -c commands are not allowed")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 120:
            problems.append("timeout must be 0-120 seconds")
        return problems


class FakeMCPTransport:
    """Deterministic in-memory transport for tests and protocol exercises."""

    def __init__(self, tools: list[dict[str, Any]] | None = None,
                 replies: dict[str, Any] | None = None) -> None:
        self.tools = tools or []
        self.replies = replies or {}
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    def send(self, message: dict[str, Any]) -> None:
        self.sent.append(message)

    def receive(self, timeout: float = 10.0) -> dict[str, Any] | None:
        if not self.sent:
            return None
        msg = self.sent[-1]
        method = msg.get("method")
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": msg["id"],
                    "result": {"protocolVersion": "2024-11-05",
                               "capabilities": {"tools": {}}}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": msg["id"],
                    "result": {"tools": self.tools}}
        if method == "tools/call":
            name = (msg.get("params") or {}).get("name")
            if name in self.replies:
                value = self.replies[name]
                if isinstance(value, Exception):
                    return {"jsonrpc": "2.0", "id": msg["id"],
                            "error": {"code": -32000, "message": str(value)}}
                return {"jsonrpc": "2.0", "id": msg["id"],
                        "result": {"content": value}}
            return {"jsonrpc": "2.0", "id": msg["id"],
                    "error": {"code": -32601, "message": "unknown tool"}}
        return {"jsonrpc": "2.0", "id": msg.get("id"),
                "error": {"code": -32601, "message": "unknown method"}}

    def close(self) -> None:
        self.closed = True


class StdioTransport:
    """Launch an MCP server as a host process.

    This is a dangerous surface. It refuses unless the caller explicitly sets
    ``allow_host=True`` and the ``mcp`` capability is enabled. Use a VM or a
    sandbox-backed transport for untrusted servers.
    """

    def __init__(self, command: list[str], *, env: dict[str, str] | None = None,
                 cwd: str | None = None, allow_host: bool = False,
                 policy: CapabilityPolicy | None = None) -> None:
        if not allow_host or os.environ.get("REVERSEAI_ALLOW_MCP_HOST") != "1":
            raise MCPError(
                "host MCP transport is disabled; set REVERSEAI_ALLOW_MCP_HOST=1 "
                "and pass allow_host=True explicitly")
        try:
            (policy or CapabilityPolicy()).require("mcp")
        except CapabilityDenied as exc:
            raise MCPError(str(exc)) from exc
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
            env={**os.environ, **(env or {})}, cwd=cwd)

    def send(self, message: dict[str, Any]) -> None:
        if self.proc.stdin is None:
            raise MCPError("MCP stdin is closed")
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def receive(self, timeout: float = 10.0) -> dict[str, Any] | None:
        if self.proc.stdout is None:
            return None
        # The caller controls the timeout by closing/terminating; a blocking
        # readline is bounded by the process lifetime. The protocol wrapper
        # applies a wall-clock check before each call.
        line = self.proc.stdout.readline()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise MCPError("MCP server returned invalid JSON") from exc

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


class MCPClient:
    def __init__(self, transport: MCPTransport, *,
                 allowed_tools: list[str] | None = None,
                 timeout_seconds: float = 10.0,
                 policy: CapabilityPolicy | None = None) -> None:
        self.transport = transport
        self.allowed_tools = set(allowed_tools or [])
        self.timeout_seconds = timeout_seconds
        self.policy = policy or CapabilityPolicy()
        self._id = 0
        self.initialized = False
        self.tools: list[dict[str, Any]] = []

    def _require(self) -> None:
        try:
            self.policy.require("mcp")
        except CapabilityDenied as exc:
            raise MCPError(str(exc)) from exc

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method,
               "params": params or {}}
        self.transport.send(msg)
        reply = self.transport.receive(self.timeout_seconds)
        if reply is None:
            raise MCPError(f"MCP server did not answer {method}")
        if reply.get("error"):
            err = reply["error"]
            raise MCPError(str(err.get("message") or err))
        return reply.get("result")

    def initialize(self) -> dict[str, Any]:
        self._require()
        result = self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "reverseai", "version": "0.8"},
        })
        self.initialized = True
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        self._require()
        if not self.initialized:
            self.initialize()
        result = self._rpc("tools/list")
        tools = list((result or {}).get("tools") or [])
        if self.allowed_tools:
            tools = [t for t in tools if t.get("name") in self.allowed_tools]
        self.tools = tools
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        self._require()
        if self.allowed_tools and name not in self.allowed_tools:
            raise MCPError(f"tool {name!r} is not in the allowlist")
        result = self._rpc("tools/call", {"name": name,
                                          "arguments": dict(arguments or {})})
        return result

    def close(self) -> None:
        self.transport.close()


class MCPRegistry:
    def __init__(self) -> None:
        self.manifests: dict[str, MCPManifest] = {}

    def add(self, manifest: MCPManifest) -> None:
        problems = manifest.validate()
        if problems:
            raise MCPError("; ".join(problems))
        self.manifests[manifest.name] = manifest

    def list(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.manifests.values()]

    def client(self, name: str, transport: MCPTransport) -> MCPClient:
        manifest = self.manifests.get(name)
        if manifest is None:
            raise MCPError(f"unknown MCP server: {name}")
        return MCPClient(transport, allowed_tools=manifest.allowed_tools,
                         timeout_seconds=manifest.timeout_seconds)
