"""Zero-dependency HTTP control API built on http.server.

Endpoints (JSON in / JSON out):
  GET  /health            -> {status, version}
  GET  /caps              -> host capabilities
  POST /analyze           {path}                 -> AnalysisReport
  POST /diff              {a, b}                  -> BinaryDiff
  GET  /jobs              -> [job summaries]
  GET  /jobs/<id>         -> full job record
  POST /jobs              {goal, target?, project_dir?, provider?, permission?,
                           max_steps?}            -> full job record (runs synchronously)

Security: localhost-only by default; request bodies are size-capped; job ids are
validated against path traversal by the store.
"""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .. import __version__
from ..agent import Agent, Permission, get_provider
from ..agent.store import JobStore
from ..core import analyze_file
from ..core.diff import diff_files
from ..sandbox import detect_capabilities
from ..security.validate import ValidationError

_MAX_BODY = 1 * 1024 * 1024
_PERM = {"read": Permission.READ, "execute": Permission.EXECUTE, "write": Permission.WRITE}
_JOB_PATH = re.compile(r"^/jobs/(job_[A-Za-z0-9]+)$")


class _Handler(BaseHTTPRequestHandler):
    store: JobStore = None  # type: ignore[assignment]
    server_version = f"ReverseAI/{__version__}"

    # Quieter logging; override to integrate a real logger later.
    def log_message(self, fmt, *args):  # noqa: N802
        pass

    # --- helpers ---
    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any] | None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return {}
        if length > _MAX_BODY:
            self._send(413, {"error": "request body too large"})
            return None
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, {"error": "invalid JSON body"})
            return None
        if not isinstance(data, dict):
            self._send(400, {"error": "body must be a JSON object"})
            return None
        return data

    # --- routing ---
    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            return self._send(200, {"status": "ok", "version": __version__})
        if self.path == "/caps":
            return self._send(200, detect_capabilities().to_dict())
        if self.path == "/jobs":
            return self._send(200, {"jobs": self.store.list_summaries()})
        m = _JOB_PATH.match(self.path)
        if m:
            rec = self.store.get(m.group(1))
            if rec is None:
                return self._send(404, {"error": "job not found"})
            return self._send(200, rec)
        return self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        body = self._read_json()
        if body is None:
            return
        if self.path == "/analyze":
            return self._analyze(body)
        if self.path == "/diff":
            return self._diff(body)
        if self.path == "/jobs":
            return self._run_job(body)
        return self._send(404, {"error": "not found"})

    # --- handlers ---
    def _analyze(self, body):
        path = body.get("path")
        if not path:
            return self._send(400, {"error": "missing 'path'"})
        try:
            report = analyze_file(path)
        except (ValidationError, OSError) as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(200, report.to_dict())

    def _diff(self, body):
        a, b = body.get("a"), body.get("b")
        if not a or not b:
            return self._send(400, {"error": "missing 'a' or 'b'"})
        try:
            d = diff_files(a, b)
        except (ValidationError, OSError) as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(200, d.to_dict())

    def _run_job(self, body):
        goal = body.get("goal")
        if not goal:
            return self._send(400, {"error": "missing 'goal'"})
        provider_name = body.get("provider", "deepseek")
        perm = _PERM.get(body.get("permission", "execute"))
        if perm is None:
            return self._send(400, {"error": "permission must be read|execute|write"})
        try:
            provider = get_provider(provider_name)
        except Exception as exc:  # provider/config error
            return self._send(400, {"error": f"provider error: {exc}"})

        agent = Agent(provider, max_permission=perm,
                      max_steps=int(body.get("max_steps", 24)))
        try:
            job = agent.run(goal, target_path=body.get("target"),
                            project_dir=body.get("project_dir"))
        except Exception as exc:
            return self._send(500, {"error": f"job failed: {exc}"})
        self.store.save(job)
        return self._send(200, job.to_dict())


class ReverseAIServer:
    """Thin wrapper owning the ThreadingHTTPServer and its store."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8077,
                 store_dir: str = "./jobs") -> None:
        store = JobStore(store_dir)
        handler = type("BoundHandler", (_Handler,), {"store": store})
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.store = store

    @property
    def address(self) -> tuple[str, int]:
        return self.httpd.server_address[0], self.httpd.server_address[1]

    def serve_forever(self) -> None:
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def serve(host: str = "127.0.0.1", port: int = 8077, store_dir: str = "./jobs") -> None:
    srv = ReverseAIServer(host, port, store_dir)
    h, p = srv.address
    print(f"ReverseAI control API on http://{h}:{p}  (store: {store_dir})")
    print("Local-only control surface — do not expose to untrusted networks.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
