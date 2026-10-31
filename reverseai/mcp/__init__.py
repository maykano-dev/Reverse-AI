"""MCP protocol surface.

The client is transport-agnostic. A host-process transport is explicitly marked
dangerous; production use must put the server behind a sandbox/VM boundary.
"""

from .client import (
    FakeMCPTransport, MCPClient, MCPError, MCPManifest, MCPRegistry,
    StdioTransport,
)
from .server import MCPServer, server_tools

__all__ = [
    "MCPClient", "MCPManifest", "MCPRegistry", "MCPError",
    "FakeMCPTransport", "StdioTransport",
    "MCPServer", "server_tools",
]
