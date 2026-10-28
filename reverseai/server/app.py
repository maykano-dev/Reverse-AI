"""Zero-dependency HTTP control API built on http.server.

Endpoints (JSON in / JSON out):
  GET  /health            -> {status, version}
  GET  /config            -> readiness + feature flags (never the model)
  GET  /caps              -> host capabilities
  GET  /capabilities      -> high-risk capability policy (deny by default)
  GET  /surfaces          -> dangerous-surface inventory (no secrets)
  GET  /templates         -> agent roles / squads
  GET  /skills            -> installed playbooks
  GET  /memory            -> long-term notes
  POST /memory            {text, tags?}
  DELETE /memory/<id>
  GET  /routines          -> scheduled tasks
  POST /routines          {name, goal, schedule, template?, target?}
  DELETE /routines/<id>
  POST /routines/<id>/run
  GET  /usage             -> tokens + estimated cost
  POST /feedback          {job_id, rating, note?}
  POST /analyze           {path}                 -> AnalysisReport
  POST /diff              {a, b}                 -> BinaryDiff
  POST /world             {path}                 -> world model summary
  POST /discover          {path, ...}            -> ranked opportunities
  POST /modify            {target, patches}      -> patch result + download
  POST /verify            {original, modified}   -> behavioral comparison
  POST /clone             {url, rename_*}        -> clone result + download
  GET  /jobs              -> one summary per conversation (?all=1 for turns)
  GET  /jobs/<id>         -> full job record
  GET  /jobs/<id>/events?after=N -> SSE (durable, replayable)
  GET  /jobs/<id>/surfaces -> interactive surfaces
  POST /jobs/<id>/surfaces/<surface>/events -> record an interaction
  POST /jobs/<id>/surfaces/<surface>/respond -> record + continue the agent
  POST /jobs/start        {goal, target?, template?, permission?, conversation_id?}
  POST /jobs              {goal, target?, ...}   -> full job record (synchronous)
  PUT  /upload            raw bytes, X-Filename header

Security: localhost by default; optional bearer auth via REVERSEAI_AUTH_TOKEN;
request bodies are size-capped; job ids are validated against path traversal.
When auth is enabled, filesystem paths are confined to the store, the working
directory, and REVERSEAI_ALLOWED_ROOTS.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .. import __version__
from ..agent import Agent, Permission, get_provider
from ..agent.memory import MemoryStore
from ..agent.skills import load_skills
from ..agent.store import JobStore
from ..agent.templates import all_templates
from ..core.analyze import analyze_bytes
from ..core.diff import diff_reports
from ..naming import safe_download_name
from ..routines import RoutineScheduler, RoutineStore
from ..sandbox import detect_capabilities
from ..surface import (
    SurfaceError, SurfaceEventStore, event_from_body, find_surface,
)
from ..security.validate import ValidationError, read_target
from ..util.logging import get_logger
from .runs import RunManager

_log = get_logger("reverseai.server")

_MAX_BODY = 1 * 1024 * 1024
# Large binaries/archives are accepted, but not without a bound: a public
# instance must not be able to fill the data disk with one request.
_UPLOAD_MAX = int(os.environ.get("REVERSEAI_UPLOAD_MAX_MB", "512")) * 1024 * 1024
_PERM = {"read": Permission.READ, "execute": Permission.EXECUTE, "write": Permission.WRITE}
_JOB_PATH = re.compile(r"^/jobs/(job_[A-Za-z0-9]+)$")
_EVENTS_PATH = re.compile(r"^/jobs/(job_[A-Za-z0-9]+)/events$")
_JOB_ARTIFACT_PATH = re.compile(r"^/jobs/(job_[A-Za-z0-9]+)/artifact$")
_JOB_REPORT_PATH = re.compile(r"^/jobs/(job_[A-Za-z0-9]+)/report$")
_JOB_REPORT_HTML_PATH = re.compile(r"^/jobs/(job_[A-Za-z0-9]+)/report\.html$")
_ARTIFACT_PATH = re.compile(r"^/conversations/(conv_[A-Za-z0-9]+)/artifact$")
_FILES_PATH = re.compile(r"^/files/([a-f0-9]{12})/([A-Za-z0-9._-]+)$")
_PREVIEW_PATH = re.compile(r"^/preview/(conv_[A-Za-z0-9]+)/(.*)$")
_PREVIEW_EVENTS_PATH = re.compile(r"^/preview/(conv_[A-Za-z0-9]+)/__events$")
_PREVIEW_RELOAD_PATH = re.compile(r"^/preview/(conv_[A-Za-z0-9]+)/__reload\.js$")
_MEMORY_PATH = re.compile(r"^/memory/(mem_[A-Za-z0-9]+)$")
_ROUTINE_PATH = re.compile(r"^/routines/(rt_[A-Za-z0-9]+)$")
_ROUTINE_RUN_PATH = re.compile(r"^/routines/(rt_[A-Za-z0-9]+)/run$")
_JOB_CANCEL_PATH = re.compile(r"^/jobs/(job_[A-Za-z0-9]+)/cancel$")
_JOB_SURFACES_PATH = re.compile(r"^/jobs/(job_[A-Za-z0-9]+)/surfaces$")
_SURFACE_EVENT_PATH = re.compile(
    r"^/jobs/(job_[A-Za-z0-9]+)/surfaces/(sf_[A-Za-z0-9]+)/events$")
_SURFACE_RESPOND_PATH = re.compile(
    r"^/jobs/(job_[A-Za-z0-9]+)/surfaces/(sf_[A-Za-z0-9]+)/respond$")
_VENDOR_PATH = re.compile(r"^/vendor/([A-Za-z0-9._-]+)$")
_STATIC_DIR = Path(__file__).parent / "static"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")

_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "frame-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


class _Handler(BaseHTTPRequestHandler):
    store: JobStore = None  # type: ignore[assignment]
    runs: RunManager = None  # type: ignore[assignment]
    memory: MemoryStore = None  # type: ignore[assignment]
    routines: RoutineStore = None  # type: ignore[assignment]
    skills: list = []
    server_version = f"ReverseAI/{__version__}"

    # Quieter logging; override to integrate a real logger later.
    def log_message(self, fmt, *args):  # noqa: N802
        pass

    # --- auth -----------------------------------------------------------
    @staticmethod
    def _token() -> str:
        return os.environ.get("REVERSEAI_AUTH_TOKEN", "").strip()

    def _token_hash(self) -> str:
        return hashlib.sha256(self._token().encode("utf-8")).hexdigest()

    def _authorized(self) -> bool:
        token = self._token()
        if not token:
            return True
        supplied = ""
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        if not supplied:
            qs = urllib.parse.urlparse(self.path).query
            supplied = (urllib.parse.parse_qs(qs).get("token") or [""])[0]
        if supplied and hmac.compare_digest(supplied, token):
            self._auth_ok = True
            return True
        cookie = self.headers.get("Cookie", "")
        if f"rvai_auth={self._token_hash()}" in cookie:
            return True
        return False

    def _auth_headers(self) -> None:
        token = self._token()
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if token and getattr(self, "_auth_ok", False):
            self.send_header(
                "Set-Cookie",
                f"rvai_auth={self._token_hash()}; Path=/; HttpOnly; SameSite=Lax")

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self.send_response(401)
        self._auth_headers()
        self.send_header("WWW-Authenticate", 'Bearer realm="ReverseAI"')
        body = json.dumps({"error": "unauthorized"}).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    # --- helpers --------------------------------------------------------
    def _send(self, code: int, payload: dict[str, Any]) -> None:
        _log.info("%s %s -> %s", self.command, self.path.split("?")[0], code)
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self._auth_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
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
            self._send(400, {"body must be a JSON object"})
            return None
        return data

    def _allowed_roots(self) -> list[Path]:
        # Local mode (no token) may read the working directory for convenience.
        # A public instance is confined to the store and explicit roots.
        roots = [self.store.dir]
        if not self._token():
            roots.append(Path.cwd())
        extra = os.environ.get("REVERSEAI_ALLOWED_ROOTS", "")
        roots += [Path(p) for p in extra.split(os.pathsep) if p.strip()]
        out: list[Path] = []
        for p in roots:
            try:
                out.append(p.resolve())
            except OSError:
                continue
        return out

    def _path_error(self, path: str | None) -> str | None:
        """Return an error when a public deployment is asked for an outside path."""
        if not path or not self._token():
            return None
        try:
            target = Path(path).resolve()
        except OSError:
            return "invalid path"
        for root in self._allowed_roots():
            try:
                target.relative_to(root)
                return None
            except ValueError:
                continue
        return "path is outside the allowed roots for this server"

    def _analyze_path(self, path: str):
        p = Path(path)
        # Resolve a symlink (e.g. /usr/bin/objdump on Debian) before the
        # no-symlink read guard; the resolved path is what gets size-capped.
        if p.is_symlink():
            p = p.resolve()
        data = read_target(p)
        return analyze_bytes(data, path=str(p))

    # --- routing --------------------------------------------------------
    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            # The shell is public so the login screen can load; every API call
            # behind it is still authenticated.
            return self._send_static("index.html", "text/html; charset=utf-8", csp=True)
        if path in ("/app.js", "/style.css", "/manifest.webmanifest", "/sw.js", "/icon.svg"):
            return self._serve_asset(path)
        vm = _VENDOR_PATH.match(path)
        if vm:
            return self._serve_asset(f"/vendor/{vm.group(1)}")
        if path == "/health":
            return self._send(200, {"status": "ok", "version": __version__})
        if path == "/config":
            return self._send(200, self._config_payload())

        if not self._require_auth():
            return

        if path == "/caps":
            caps = detect_capabilities()
            payload = caps.to_dict()
            payload["can_run_untrusted"] = caps.can_run_untrusted()
            payload["best_isolation"] = caps.best_isolation()
            return self._send(200, payload)
        if path == "/capabilities":
            from ..security.capabilities import CapabilityPolicy

            return self._send(200, {
                "default": "deny",
                "capabilities": CapabilityPolicy().status(),
            })
        if path == "/surfaces":
            from ..surfaces import surface_status

            return self._send(200, surface_status())
        if path == "/templates":
            return self._send(200, {"templates": [t.to_dict() for t in all_templates()]})
        if path == "/skills":
            return self._send(200, {"skills": [s.to_dict() for s in self.skills]})
        if path == "/memory":
            return self._send(200, {"notes": self.memory.all()})
        if path == "/routines":
            return self._send(200, {"routines": [_routine_json(r) for r in self.routines.all()]})
        if path == "/usage":
            return self._send(200, self.store.usage_summary())
        if path == "/feedback":
            return self._send(200, {"feedback": self.store.feedback()})
        if path == "/jobs":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if qs.get("all", ["0"])[0] in ("1", "true", "yes"):
                return self._send(200, {"jobs": self.store.list_summaries(),
                                        "grouped": False})
            return self._send(200, {"jobs": self.store.list_conversations(),
                                    "grouped": True})

        em = _EVENTS_PATH.match(path)
        if em:
            return self._stream_events(em.group(1))
        am = _ARTIFACT_PATH.match(path)
        if am:
            return self._download_artifact(am.group(1))
        jam = _JOB_ARTIFACT_PATH.match(path)
        if jam:
            return self._download_job_artifact(jam.group(1))
        jrm = _JOB_REPORT_PATH.match(path)
        if jrm:
            return self._job_report(jrm.group(1), html=False)
        jrhm = _JOB_REPORT_HTML_PATH.match(path)
        if jrhm:
            return self._job_report(jrhm.group(1), html=True)
        jsm = _JOB_SURFACES_PATH.match(path)
        if jsm:
            rec = self.store.get(jsm.group(1))
            if rec is None:
                return self._send(404, {"error": "job not found"})
            return self._send(200, {"surfaces": rec.get("surfaces") or []})
        fm = _FILES_PATH.match(path)
        if fm:
            return self._download_output(fm.group(1), fm.group(2))
        em = _PREVIEW_EVENTS_PATH.match(path)
        if em:
            return self._preview_events(em.group(1))
        rm = _PREVIEW_RELOAD_PATH.match(path)
        if rm:
            return self._preview_reload_js(rm.group(1))
        pm = _PREVIEW_PATH.match(path)
        if pm:
            return self._serve_preview(pm.group(1), pm.group(2))
        if path == "/proxy":
            return self._proxy_browse()
        m = _JOB_PATH.match(path)
        if m:
            rec = self.store.get(m.group(1))
            if rec is None:
                return self._send(404, {"error": "job not found"})
            if not rec.get("preview"):
                # Backfill for jobs recorded before preview metadata existed.
                from ..preview import preview_entry
                rec["preview"] = preview_entry(rec.get("workspace"))
            if rec.get("conversation_id"):
                # A surface belongs to the conversation, not just the turn that
                # created it. The sidebar opens the latest job, so aggregate the
                # history here to keep decisions and approvals visible.
                rec["surfaces"] = self.store.surfaces_for_conversation(
                    rec["conversation_id"])
            return self._send(200, rec)
        return self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if not self._require_auth():
            return
        body = self._read_json()
        if body is None:
            return
        if self.path == "/analyze":
            return self._analyze(body)
        if self.path == "/diff":
            return self._diff(body)
        if self.path == "/world":
            return self._world(body)
        if self.path == "/discover":
            return self._discover(body)
        if self.path == "/modify":
            return self._api_modify(body)
        if self.path == "/verify":
            return self._api_verify(body)
        if self.path == "/clone":
            return self._api_clone(body)
        if self.path == "/jobs":
            return self._run_job(body)
        if self.path == "/jobs/start":
            return self._start_run(body)
        cm = _JOB_CANCEL_PATH.match(self.path)
        if cm:
            ok = self.runs.cancel(cm.group(1))
            return self._send(200 if ok else 404,
                              {"cancelled": ok, "id": cm.group(1)})
        sm = _SURFACE_EVENT_PATH.match(self.path)
        if sm:
            return self._surface_event(sm.group(1), sm.group(2), body)
        srm = _SURFACE_RESPOND_PATH.match(self.path)
        if srm:
            return self._surface_respond(srm.group(1), srm.group(2), body)
        if self.path == "/memory":
            return self._memory_add(body)
        if self.path == "/routines":
            return self._routine_create(body)
        rm = _ROUTINE_RUN_PATH.match(self.path)
        if rm:
            return self._routine_run(rm.group(1))
        if self.path == "/feedback":
            return self._feedback(body)
        return self._send(404, {"error": "not found"})

    def do_PUT(self):  # noqa: N802
        if not self._require_auth():
            return
        # File upload: raw bytes with X-Filename header, streamed to disk.
        if self.path == "/upload":
            return self._upload()
        return self._send(404, {"error": "not found"})

    def do_DELETE(self):  # noqa: N802
        if not self._require_auth():
            return
        path = self.path.split("?", 1)[0]
        mm = _MEMORY_PATH.match(path)
        if mm:
            ok = self.memory.delete(mm.group(1))
            return self._send(200 if ok else 404, {"deleted": ok, "id": mm.group(1)})
        rm = _ROUTINE_PATH.match(path)
        if rm:
            ok = self.routines.delete(rm.group(1))
            return self._send(200 if ok else 404, {"deleted": ok, "id": rm.group(1)})
        m = _JOB_PATH.match(path)
        if m:
            ok = self.store.delete(m.group(1))
            return self._send(200 if ok else 404,
                              {"deleted": ok, "id": m.group(1)})
        return self._send(404, {"error": "not found"})

    # --- static + streaming --------------------------------------------
    def _serve_asset(self, path: str) -> None:
        rel = path.lstrip("/")
        if ".." in rel or rel.startswith("/"):
            return self._send(404, {"error": "not found"})
        full = (_STATIC_DIR / rel).resolve()
        try:
            full.relative_to(_STATIC_DIR.resolve())
        except ValueError:
            return self._send(404, {"error": "not found"})
        mime = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".webmanifest": "application/manifest+json",
        }.get(full.suffix.lower(), "application/octet-stream")
        try:
            data = full.read_bytes()
        except OSError:
            return self._send(404, {"error": "not found"})
        self.send_response(200)
        self._auth_headers()
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if full.suffix == ".html":
            self.send_header("Content-Security-Policy", _CSP)
        self.end_headers()
        self.wfile.write(data)

    def _send_static(self, name: str, content_type: str, csp: bool = False) -> None:
        path = _STATIC_DIR / name
        try:
            data = path.read_bytes()
        except OSError:
            return self._send(404, {"error": "UI not found"})
        _log.info("GET %s -> 200 (static)", self.path)
        self.send_response(200)
        self._auth_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if csp:
            self.send_header("Content-Security-Policy", _CSP)
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _config_payload() -> dict[str, Any]:
        """Readiness + features. Never reveals which model/provider is active."""
        import os

        from ..agent import get_provider
        from ..ocr import ocr_available, unlimited_ocr_available

        name = os.environ.get("REVERSEAI_PROVIDER", "deepseek")
        try:
            get_provider(name)
            ready = True
        except Exception:
            ready = False
        from ..security.capabilities import CapabilityPolicy

        cap_policy = CapabilityPolicy().status()
        enabled_high_risk = [n for n, d in cap_policy.items() if d.get("allowed")]
        return {
            "ready": ready,
            "auth_required": bool(os.environ.get("REVERSEAI_AUTH_TOKEN", "").strip()),
            "version": __version__,
            "capability_policy": {
                "default": "deny",
                "enabled_high_risk": enabled_high_risk,
            },
            "provider": "configured" if ready else "missing",
            "features": {
                "memory": True,
                "research": True,
                "routines": True,
                "templates": True,
                "sources": True,
                "usage": True,
                "feedback": True,
                "durable_runs": True,
                "verification": True,
                "differential_testing": True,
                "signed_reports": True,
                "behavioral_corpora": True,
            },
            "ocr": {
                "unlimited": unlimited_ocr_available(),
                "tesseract": ocr_available(),
            },
            "budget_usd": _budget(),
            "templates": [t.id for t in all_templates()],
        }

    def _start_run(self, body) -> None:
        stream_id, conversation_id, error = self.runs.start(body)
        if error:
            code = 402 if error.startswith("monthly budget") else (
                409 if "no longer available" in error else 400)
            return self._send(code, {"error": error})
        return self._send(200, {"job_id": stream_id, "conversation_id": conversation_id})

    def _upload(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return self._send(400, {"error": "empty upload"})
        if length > _UPLOAD_MAX:
            return self._send(413, {"error": f"file too large (> {_UPLOAD_MAX} bytes)"})
        raw_name = self.headers.get("X-Filename", "upload.bin")
        safe = _SAFE_NAME.sub("_", Path(raw_name).name)[:200] or "upload.bin"
        import uuid
        uploads = Path(self.store.dir) / "uploads" / uuid.uuid4().hex[:12]
        uploads.mkdir(parents=True, exist_ok=True)
        dest = uploads / safe
        written = 0
        try:
            with open(dest, "wb") as fh:
                remaining = length
                while remaining > 0:
                    chunk = self.rfile.read(min(1024 * 256, remaining))
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > _UPLOAD_MAX:
                        raise OSError("exceeded limit")
                    fh.write(chunk)
                    remaining -= len(chunk)
        except OSError as exc:
            dest.unlink(missing_ok=True)
            return self._send(400, {"error": f"upload failed: {exc}"})
        # Browsers do not preserve the execute bit. The uploaded file is never
        # run on the host; it is only exposed read-only inside the sandbox. Give
        # the owner execute permission so a native binary can be verified.
        try:
            os.chmod(dest, 0o700)
        except OSError:
            pass
        kind, arch, bits = "unknown", None, None
        import mimetypes
        mime = mimetypes.guess_type(safe)[0] or self.headers.get("Content-Type") or "application/octet-stream"
        try:
            from ..core.identify import detect_format
            from ..security.archive import is_archive
            with dest.open("rb") as fh:
                head = fh.read(512)
            fmt = detect_format(head)
            kind = fmt.value if fmt.value != "unknown" else (is_archive(head) or "unknown")
            if fmt.value != "unknown" and written <= 256 * 1024 * 1024:
                rep = self._analyze_path(str(dest))
                arch, bits = rep.arch.value, rep.bits
        except Exception:
            pass
        return self._send(200, {"path": str(dest), "filename": safe,
                                "size": written, "kind": kind, "mime": mime,
                                "arch": arch, "bits": bits})

    def _download_artifact(self, cid: str) -> None:
        self._serve_file(self.runs.artifact_path(cid), "no artifact for this conversation")

    def _download_job_artifact(self, job_id: str) -> None:
        p = self.store.artifact_for(job_id)
        self._serve_file(str(p) if p else None, "no artifact for this job")

    def _job_report(self, job_id: str, html: bool) -> None:
        from ..verify import build_from_job, render_html, render_json

        record = self.store.get(job_id)
        if record is None:
            return self._send(404, {"error": "job not found"})
        report = build_from_job(record)
        if html:
            body = render_html(report).encode("utf-8")
            self.send_response(200)
            self._auth_headers()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                "base-uri 'none'; form-action 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        body = render_json(report).encode("utf-8")
        self.send_response(200)
        self._auth_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, path, not_found_msg: str) -> None:
        if not path:
            return self._send(404, {"error": not_found_msg})
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            return self._send(404, {"error": str(exc)})
        name = safe_download_name(Path(path).name.split("__", 1)[-1])
        self.send_response(200)
        self._auth_headers()
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _stream_events(self, job_id: str) -> None:
        qs = urllib.parse.urlparse(self.path).query
        after = (urllib.parse.parse_qs(qs).get("after") or ["0"])[0]
        try:
            after_n = int(after)
        except ValueError:
            after_n = 0
        self.send_response(200)
        self._auth_headers()
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        # The preview iframe is sandboxed without allow-same-origin, so its
        # EventSource request has origin "null". The stream only says "reload".
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            for chunk in self.runs.stream(job_id, after=after_n):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    # --- handlers -------------------------------------------------------
    def _analyze(self, body):
        path = body.get("path")
        if not path:
            return self._send(400, {"error": "missing 'path'"})
        err = self._path_error(path)
        if err:
            return self._send(403, {"error": err})
        try:
            report = self._analyze_path(path)
        except (ValidationError, OSError) as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(200, report.to_dict())

    def _record_surface_event(self, job_id: str, rec: dict, surface: dict,
                              event) -> None:
        """Persist the event and reflect the answered state on the job record."""
        self.surface_events.append(job_id, surface["id"], event)
        surface["status"] = "submitted"
        surface["last_event"] = event.to_dict()
        rec["surfaces"] = rec.get("surfaces") or []
        try:
            self.store.path_for(job_id).write_text(
                json.dumps(rec, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _surface_event(self, job_id: str, surface_id: str, body: dict) -> None:
        rec = self.store.get(job_id)
        if rec is None:
            return self._send(404, {"error": "job not found"})
        surface = find_surface(rec.get("surfaces") or [], surface_id)
        if surface is None:
            return self._send(404, {"error": "surface not found"})
        try:
            event = event_from_body(job_id, surface, body)
            self._record_surface_event(job_id, rec, surface, event)
        except SurfaceError as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(200, {"accepted": True, "event": event.to_dict()})

    def _surface_respond(self, job_id: str, surface_id: str, body: dict) -> None:
        rec = self.store.get(job_id)
        if rec is None:
            return self._send(404, {"error": "job not found"})
        surface = find_surface(rec.get("surfaces") or [], surface_id)
        if surface is None:
            return self._send(404, {"error": "surface not found"})
        try:
            event = event_from_body(job_id, surface, body)
            self._record_surface_event(job_id, rec, surface, event)
        except SurfaceError as exc:
            return self._send(400, {"error": str(exc)})
        import json as _json

        goal = (
            "[Interactive surface response]\n"
            f"Surface: {surface.get('title')} ({surface_id})\n"
            f"Action: {event.action_id}\n"
            f"Value: {_json.dumps(event.value, ensure_ascii=False)}\n"
            f"Other text: {event.other_text}\n\n"
            "Continue the task using this decision. Do not repeat the question "
            "unless the answer is still genuinely ambiguous.")
        run_body = {
            "goal": goal,
            "conversation_id": rec.get("conversation_id"),
            "target": rec.get("target_path"),
            "template": rec.get("template") or "general",
            "permission": rec.get("permission") or body.get("permission") or "read",
            "max_steps": max(1, min(int(body.get("max_steps", 24) or 24), 64)),
            "client": body.get("client", 1),
        }
        stream_id, cid, error = self.runs.start(run_body)
        if error:
            code = 402 if error.startswith("monthly budget") else 409
            return self._send(code, {"error": error})
        return self._send(202, {
            "accepted": True, "job_id": stream_id,
            "conversation_id": cid, "event": event.to_dict(),
        })

    def _world(self, body):
        from ..intelligence.world import world_from_analysis

        path = body.get("path")
        if not path:
            return self._send(400, {"error": "missing 'path'"})
        err = self._path_error(path)
        if err:
            return self._send(403, {"error": err})
        try:
            report = self._analyze_path(path)
            wm = world_from_analysis(report)
        except (ValidationError, OSError) as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(200, {"summary": wm.summary(), "world": wm.to_dict()})

    def _discover(self, body):
        from ..intelligence.discovery import DiscoveryEngine
        from ..intelligence.world import world_from_analysis

        path = body.get("path")
        if not path:
            return self._send(400, {"error": "missing 'path'"})
        err = self._path_error(path)
        if err:
            return self._send(403, {"error": err})
        try:
            report = self._analyze_path(path)
            wm = world_from_analysis(report)
            engine = DiscoveryEngine(wm)
            opps = engine.discover(
                report, corpus_present=bool(body.get("corpus_present")),
                tests_present=bool(body.get("tests_present")))
        except (ValidationError, OSError) as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(200, {
            "summary": engine.summary(),
            "world": wm.summary(),
            "opportunities": [o.to_dict() for o in opps],
            "hypotheses": [h.to_dict() for h in engine.hypotheses()],
            "mission": engine.mission(max_steps=6, max_effort=15),
            "note": "This is a plan, not permission to modify the system.",
        })

    def _diff(self, body):
        a, b = body.get("a"), body.get("b")
        if not a or not b:
            return self._send(400, {"error": "missing 'a' or 'b'"})
        for p in (a, b):
            err = self._path_error(p)
            if err:
                return self._send(403, {"error": err})
        try:
            d = diff_reports(self._analyze_path(a), self._analyze_path(b))
        except (ValidationError, OSError) as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(200, d.to_dict())

    # --- engine REST endpoints -----------------------------------------
    def _api_out(self) -> tuple[Path, str]:
        import uuid

        token = uuid.uuid4().hex[:12]
        out = Path(self.store.dir) / "api_outputs" / token
        out.mkdir(parents=True, exist_ok=True)
        return out, token

    def _api_modify(self, body):
        from ..modify import BytePatch, PatchError, apply_byte_patches

        target = body.get("target")
        patches_in = body.get("patches")
        if not target or not isinstance(patches_in, list) or not patches_in:
            return self._send(400, {"error": "need 'target' and non-empty 'patches'"})
        err = self._path_error(target)
        if err:
            return self._send(403, {"error": err})
        try:
            patches = [
                BytePatch(offset=int(p["offset"]), data=bytes.fromhex(p["hex"]),
                          expected_original=bytes.fromhex(p["expect_hex"]) if p.get("expect_hex") else None)
                for p in patches_in
            ]
        except (KeyError, ValueError, PatchError) as exc:
            return self._send(400, {"error": f"bad patch spec: {exc}"})
        out, token = self._api_out()
        try:
            res = apply_byte_patches(target, patches, out)
        except (PatchError, ValidationError, OSError) as exc:
            return self._send(400, {"error": str(exc)})
        d = res.to_dict()
        d["download"] = f"/files/{token}/{Path(res.output_path).name}"
        return self._send(200, d)

    def _api_verify(self, body):
        from ..verify import compare_execution

        original, modified = body.get("original"), body.get("modified")
        if not original or not modified:
            return self._send(400, {"error": "need 'original' and 'modified'"})
        for p in (original, modified):
            err = self._path_error(p)
            if err:
                return self._send(403, {"error": err})
        report = compare_execution(original, modified, body.get("args", []))
        return self._send(200 if report.ran else 400, report.to_dict())

    def _api_clone(self, body):
        import shutil

        from ..clone import CloneError, clone_best

        url = body.get("url")
        if not url:
            return self._send(400, {"error": "need 'url'"})
        out, token = self._api_out()
        try:
            res = clone_best(url, out / "site",
                             rename_from=body.get("rename_from"),
                             rename_to=body.get("rename_to"))
        except (CloneError, OSError) as exc:
            return self._send(400, {"error": str(exc)})
        zip_path = shutil.make_archive(str(out / "site_clone"), "zip", str(out / "site"))
        d = res.to_dict()
        d["download"] = f"/files/{token}/{Path(zip_path).name}"
        return self._send(200, d)

    def _proxy_browse(self) -> None:
        from ..clone.proxy import ProxyError, fetch, rewrite_html

        qs = urllib.parse.urlparse(self.path).query
        url = urllib.parse.parse_qs(qs).get("url", [None])[0]
        if not url:
            return self._send(400, {"error": "missing url"})
        try:
            data, ctype, final_url = fetch(url)
        except ProxyError as exc:
            page = ("<!doctype html><meta charset=utf-8>"
                    "<body style='font-family:system-ui;padding:40px;color:#444'>"
                    f"<h3>Could not open this page</h3><p>{_html_escape(str(exc))}</p>"
                    "</body>")
            return self._serve_raw(page.encode(), "text/html; charset=utf-8")
        is_html = "text/html" in ctype.lower() or (
            not ctype and data[:15].lstrip().lower().startswith(b"<!doctype"))
        if is_html:
            html = rewrite_html(data.decode("utf-8", "replace"), final_url)
            return self._serve_raw(html.encode("utf-8"), "text/html; charset=utf-8")
        return self._serve_raw(data, ctype or "application/octet-stream")

    def _serve_raw(self, data: bytes, ctype: str) -> None:
        self.send_response(200)
        self._auth_headers()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_preview(self, cid: str, relpath: str) -> None:
        import mimetypes

        conv = self.runs.conversation(cid)
        if conv is None:
            return self._send(404, {"error": "no such session"})
        root = Path(conv.workspace).resolve()
        if not root.is_dir():
            return self._send(404, {"error": "nothing built to preview yet"})
        rel = (relpath or "index.html").lstrip("/")
        # The generated site can live at the workspace root, under site/, or
        # under clone/ (the website-clone layout). Keep the old clone URLs
        # working while also exposing files written by the coding tools.
        candidates = [root / rel, root / "site" / rel, root / "clone" / rel]
        target = None
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                resolved.relative_to(root)
            except (OSError, ValueError):
                continue
            if resolved.is_dir():
                resolved = resolved / "index.html"
            if resolved.is_file():
                target = resolved
                break
        if target is None:
            return self._send(404, {"error": "not found"})
        try:
            data = target.read_bytes()
        except OSError:
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if "text/html" in ctype.lower():
            text = data.decode("utf-8", "replace")
            tag = f'<script src="/preview/{cid}/__reload.js"></script>'
            if "</body>" in text.lower():
                idx = text.lower().rfind("</body>")
                text = text[:idx] + tag + text[idx:]
            else:
                text += tag
            data = text.encode("utf-8")
        self.send_response(200)
        self._auth_headers()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _preview_reload_js(self, cid: str) -> None:
        body = (
            "const u = new URL('/preview/" + cid + "/__events', location.href);\n"
            "const token = new URL(location.href).searchParams.get('token');\n"
            "if (token) u.searchParams.set('token', token);\n"
            "const es = new EventSource(u.toString());\n"
            "let t;\n"
            "es.addEventListener('reload', () => {\n"
            "  clearTimeout(t); t = setTimeout(() => location.reload(), 300);\n"
            "});\n"
        ).encode()
        self.send_response(200)
        self._auth_headers()
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _preview_events(self, cid: str) -> None:
        from ..preview import preview_snapshot
        conv = self.runs.conversation(cid)
        if conv is None:
            return self._send(404, {"error": "no such session"})
        self.send_response(200)
        self._auth_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        # The preview iframe is sandboxed without allow-same-origin, so its
        # EventSource request has origin "null". The stream only says "reload".
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        last = preview_snapshot(conv.workspace)
        deadline = time.monotonic() + 1800
        beat = time.monotonic() + 12
        try:
            self.wfile.write(b"retry: 800\n\n")
            self.wfile.flush()
            while time.monotonic() < deadline:
                time.sleep(0.6)
                now = preview_snapshot(conv.workspace)
                if now != last:
                    last = now
                    self.wfile.write(b"event: reload\ndata: reload\n\n")
                    self.wfile.flush()
                    beat = time.monotonic() + 12
                elif time.monotonic() >= beat:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    beat = time.monotonic() + 12
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.close_connection = True

    def _download_output(self, token: str, name: str) -> None:
        base = (Path(self.store.dir) / "api_outputs" / token).resolve()
        target = (base / name).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return self._send(404, {"error": "not found"})
        self._serve_file(str(target) if target.is_file() else None, "not found")

    def _run_job(self, body):
        goal = body.get("goal")
        if not goal:
            return self._send(400, {"error": "missing 'goal'"})
        for p in (body.get("target"), body.get("project_dir")):
            err = self._path_error(p)
            if err:
                return self._send(403, {"error": err})
        provider_name = os.environ.get("REVERSEAI_PROVIDER") or body.get("provider", "deepseek")
        perm = _PERM.get(body.get("permission", "execute"))
        if perm is None:
            return self._send(400, {"error": "permission must be read|execute|write"})
        try:
            provider = get_provider(provider_name)
        except Exception as exc:
            return self._send(400, {"error": f"provider error: {exc}"})

        from ..agent.templates import resolve_template
        agent = Agent(provider, max_permission=perm,
                      max_steps=max(1, min(int(body.get("max_steps", 24)), 64)),
                      template=resolve_template(body.get("template"), goal),
                      memory=self.memory, skills=self.skills,
                      mode=body.get("mode"))
        try:
            job = agent.run(goal, target_path=body.get("target"),
                            project_dir=body.get("project_dir"))
        except Exception as exc:
            return self._send(500, {"error": f"job failed: {exc}"})
        if job.artifact_meta.get("path"):
            self.store.save_artifact(job.id, job.artifact_meta["path"])
        self.store.save(job)
        return self._send(200, job.to_dict())

    # --- memory / routines / feedback ----------------------------------
    def _memory_add(self, body):
        text = body.get("text")
        if not text:
            return self._send(400, {"error": "missing 'text'"})
        try:
            note = self.memory.add(text, tags=body.get("tags"), source="user")
        except ValueError as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(200, {"note": note})

    def _routine_create(self, body):
        goal = body.get("goal")
        schedule = body.get("schedule")
        if not goal or not isinstance(schedule, dict):
            return self._send(400, {"error": "need 'goal' and 'schedule' object"})
        perm = str(body.get("permission", "write")).lower()
        if perm not in _PERM:
            return self._send(400, {"error": "permission must be read|execute|write"})
        try:
            r = self.routines.add(
                body.get("name") or goal, goal, schedule,
                template=body.get("template", "general"),
                target=body.get("target"), permission=perm)
        except (ValueError, TypeError) as exc:
            return self._send(400, {"error": str(exc)})
        return self._send(200, {"routine": _routine_json(r)})

    def _routine_run(self, routine_id: str):
        r = self.routines.get(routine_id)
        if r is None:
            return self._send(404, {"error": "no such routine"})
        stream_id, _cid, error = self.runs.start({
            "goal": r.goal, "target": r.target, "template": r.template,
            "permission": r.permission,
        })
        if error:
            return self._send(400, {"error": error})
        import time

        r.last_run = time.time()
        r.last_job = stream_id
        from ..routines import compute_next

        if r.schedule.get("kind") == "once":
            r.next_run = None
            r.enabled = False
        else:
            r.next_run = compute_next(r.schedule, last_run=r.last_run)
        self.routines.update(r)
        return self._send(200, {"job_id": stream_id, "routine": _routine_json(r)})

    def _feedback(self, body):
        rating = body.get("rating")
        if rating not in ("up", "down"):
            return self._send(400, {"error": "rating must be 'up' or 'down'"})
        row = self.store.add_feedback(
            str(body.get("job_id") or ""), rating, str(body.get("note") or ""))
        return self._send(200, {"ok": True, "feedback": row})


class ReverseAIServer:
    """Thin wrapper owning the ThreadingHTTPServer, store, memory, and scheduler."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8077,
                 store_dir: str = "./jobs") -> None:
        store = JobStore(store_dir)
        memory = MemoryStore(Path(store_dir) / "memory.json")
        skills_dir = os.environ.get("REVERSEAI_SKILLS") or (Path(store_dir) / "skills")
        skills = load_skills(skills_dir)
        routines = RoutineStore(Path(store_dir) / "routines.json")
        runs = RunManager(store, memory=memory, skills=skills, routines=routines)
        self.scheduler = RoutineScheduler(routines, runs)
        surface_events = SurfaceEventStore(Path(store_dir) / "surface_events")
        handler = type("BoundHandler", (_Handler,), {
            "store": store, "runs": runs, "memory": memory,
            "routines": routines, "skills": skills,
            "surface_events": surface_events,
        })
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.store = store
        self.memory = memory
        self.routines = routines
        self.runs = runs
        self.skills = skills
        self.scheduler.start()

    @property
    def address(self) -> tuple[str, int]:
        return self.httpd.server_address[0], self.httpd.server_address[1]

    def serve_forever(self) -> None:
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        self.scheduler.stop()
        self.httpd.shutdown()
        self.httpd.server_close()


def _routine_json(r) -> dict[str, Any]:
    d = r.to_dict()
    for key in ("next_run", "last_run"):
        if d.get(key):
            import time

            d[key + "_iso"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(d[key]))
    return d


def _budget() -> float | None:
    raw = os.environ.get("REVERSEAI_MONTHLY_BUDGET", "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def serve(host: str = "127.0.0.1", port: int = 8077, store_dir: str = "./jobs") -> None:
    srv = ReverseAIServer(host, port, store_dir)
    h, p = srv.address
    auth = "on" if os.environ.get("REVERSEAI_AUTH_TOKEN", "").strip() else "off"
    print(f"ReverseAI control API on http://{h}:{p}  (store: {store_dir}, auth: {auth})")
    if auth == "off":
        print("Auth is off. Keep this bound to localhost, or set "
              "REVERSEAI_AUTH_TOKEN before exposing it.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()
