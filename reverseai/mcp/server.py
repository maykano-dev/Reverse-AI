"""Expose ReverseAI's own tools as an MCP server (stdio JSON-RPC).

This makes ReverseAI a tool *provider* for any MCP client - Claude Desktop,
Claude Code, or another agent - so they get ReverseAI's analysis, code
navigation, and git tools over the standard Model Context Protocol.

Safety, by design:
- Exposing local tools to an external process is the ``mcp`` gated capability.
  ``serve()`` refuses unless the operator has enabled it
  (``REVERSEAI_ENABLE_DANGEROUS_CAPABILITIES=1`` and ``REVERSEAI_ENABLE_MCP=1``).
- Least privilege: by default only READ-permission tools are exposed (analysis,
  search, outline, git status/diff/log, file read). Executing or writing tools
  (write_file, run_command, run_tests, git_commit, ...) appear only when the
  operator raises ``max_permission`` explicitly.
- Everything a tool RETURNS is data, never instructions - the same rule the
  agent loop follows. A client that relays this output must treat it as data.

The protocol handling is pure (``handle``), so it is fully testable in-process;
the gate applies to ``serve()``, the real external exposure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..agent.tools import Permission, ToolContext
from ..security.capabilities import CapabilityPolicy

PROTOCOL_VERSION = "2024-11-05"


def _version() -> str:
    try:
        from .. import __version__  # type: ignore
        return str(__version__)
    except Exception:
        return "0.9.0"


def server_tools(max_permission: Permission = Permission.READ) -> list:
    """The curated set of tools exposed over MCP, filtered by permission.

    A deliberately explicit allowlist (not every registered tool) - a known,
    least-privilege surface for an external client.
    """
    from ..agent.builtins import (
        AnalyzeApkTool, AnalyzeBinaryTool, AnalyzeRepositoryTool, ControlFlowTool,
        DisassembleTool, ListFunctionsTool, ListStringsTool, XRefTool,
    )
    from ..agent.code_nav_tools import CodeOutlineTool, SearchCodeTool
    from ..agent.coding_tools import (
        EditFileTool, ListDirTool, ReadFileTool, RunCommandTool, RunTestsTool,
        WriteFileTool,
    )
    from ..agent.git_tools import (
        GitBranchTool, GitCommitTool, GitDiffTool, GitLogTool, GitStatusTool,
    )

    candidates = [
        # READ: analysis + navigation + git inspection
        AnalyzeBinaryTool(), ListStringsTool(), DisassembleTool(),
        ListFunctionsTool(), ControlFlowTool(), XRefTool(),
        AnalyzeRepositoryTool(), AnalyzeApkTool(),
        ListDirTool(), ReadFileTool(), SearchCodeTool(), CodeOutlineTool(),
        GitStatusTool(), GitDiffTool(), GitLogTool(),
        # EXECUTE / WRITE: only surface when explicitly allowed
        RunCommandTool(), RunTestsTool(),
        WriteFileTool(), EditFileTool(), GitBranchTool(), GitCommitTool(),
    ]
    return [t for t in candidates if t.permission <= max_permission]


class MCPServer:
    def __init__(self, workspace: str | Path = ".",
                 max_permission: Permission = Permission.READ,
                 tools: list | None = None,
                 policy: CapabilityPolicy | None = None) -> None:
        self.workspace = str(Path(workspace).resolve())
        self.max_permission = max_permission
        tool_list = tools if tools is not None else server_tools(max_permission)
        self.tools = {t.name: t for t in tool_list}
        self.policy = policy or CapabilityPolicy()

    # --- tool execution ---------------------------------------------------
    def _context(self) -> ToolContext:
        return ToolContext(job_id="mcp", workspace=self.workspace,
                           extra={"project_dir": self.workspace})

    def descriptors(self) -> list[dict[str, Any]]:
        out = []
        for t in self.tools.values():
            out.append({
                "name": t.name,
                "description": " ".join((t.description or "").split()),
                "inputSchema": t.parameters or {"type": "object", "properties": {}},
            })
        return out

    def call(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        tool = self.tools.get(name)
        if tool is None:
            return {"content": [{"type": "text",
                                 "text": f"unknown or unexposed tool: {name}"}],
                    "isError": True}
        try:
            res = tool.run(dict(arguments or {}), self._context())
        except Exception as exc:  # pragma: no cover - defensive
            return {"content": [{"type": "text", "text": f"tool error: {exc}"}],
                    "isError": True}
        text = res.content or ("ok" if res.ok else (res.error or "failed"))
        return {"content": [{"type": "text", "text": text}], "isError": not res.ok}

    # --- protocol ---------------------------------------------------------
    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """Process one JSON-RPC message; return a reply, or None for notices."""
        mid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "initialize":
            return self._ok(mid, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "reverseai", "version": _version()},
            })
        if isinstance(method, str) and method.startswith("notifications/"):
            return None  # notifications are not answered
        if method == "ping":
            return self._ok(mid, {})
        if method == "tools/list":
            return self._ok(mid, {"tools": self.descriptors()})
        if method == "tools/call":
            return self._ok(mid, self.call(params.get("name"),
                                           params.get("arguments")))
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"unknown method: {method}"}}

    @staticmethod
    def _ok(mid: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    # --- transport --------------------------------------------------------
    def require_capability(self) -> None:
        """Raise CapabilityDenied unless the operator enabled the mcp surface."""
        self.policy.require("mcp")

    def serve(self, stdin=None, stdout=None) -> None:
        """Serve JSON-RPC over stdio until the client closes stdin.

        Gated: refuses unless the ``mcp`` capability is enabled.
        """
        self.require_capability()
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            reply = self.handle(msg)
            if reply is None:
                continue
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
