"""ReverseAI local control API (stdlib-only HTTP server).

A localhost control surface over the agent and analysis engine. It is a
single-user developer/control API, not a hardened multi-tenant service — it
accepts server-side file paths and runs jobs in-process. Bind it to 127.0.0.1
(the default) and do not expose it to untrusted networks. The multi-tenant,
upload-based product API is a later milestone.
"""

from .app import ReverseAIServer, serve

__all__ = ["ReverseAIServer", "serve"]
