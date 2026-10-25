"""ReverseAI control API and web app (stdlib HTTP server).

The server exposes the agent, analysis engine, durable runs, memory, routines,
research, and artifacts over JSON + SSE. It binds to localhost by default and
supports optional bearer auth (``REVERSEAI_AUTH_TOKEN``) plus a path allowlist
(``REVERSEAI_ALLOWED_ROOTS``) for public deployments.

See ``docs/SECURITY.md`` before exposing it to an untrusted network.
"""

from .app import ReverseAIServer, serve

__all__ = ["ReverseAIServer", "serve"]
