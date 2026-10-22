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

from pathlib import Path

from .. import __version__
from ..agent import Agent, Permission, get_provider
from ..agent.store import JobStore
from ..core import analyze_file
from ..core.diff import diff_files
from ..sandbox import detect_capabilities
from ..security.validate import ValidationError
from ..util.logging import get_logger
from .runs import RunManager

_log = get_logger("reverseai.server")

_MAX_BODY = 1 * 1024 * 1024
_UPLOAD_MAX = 4 * 1024 * 1024 * 1024  # 4 GiB — large binaries/archives accepted
_PERM = {"read": Permission.READ, "execute": Permission.EXECUTE, "write": Permission.WRITE}
_JOB_PATH = re.compile(r"^/jobs/(job_[A-Za-z0-9]+)$")
_EVENTS_PATH = re.compile(r"^/jobs/(job_[A-Za-z0-9]+)/events$")
_JOB_ARTIFACT_PATH = re.compile(r"^/jobs/(job_[A-Za-z0-9]+)/artifact$")
_ARTIFACT_PATH = re.compile(r"^/conversations/(conv_[A-Za-z0-9]+)/artifact$")
_FILES_PATH = re.compile(r"^/files/([a-f0-9]{12})/([A-Za-z0-9._-]+)$")
_PREVIEW_PATH = re.compile(r"^/preview/(conv_[A-Za-z0-9]+)/(.*)$")
_STATIC_DIR = Path(__file__).parent / "static"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


class _Handler(BaseHTTPRequestHandler):
    store: JobStore = None  # type: ignore[assignment]
    runs: RunManager = None  # type: ignore[assignment]
    server_version = f"ReverseAI/{__version__}"

    # Quieter logging; override to integrate a real logger later.
    def log_message(self, fmt, *args):  # noqa: N802
        pass

    # --- helpers ---
    def _send(self, code: int, payload: dict[str, Any]) -> None:
        _log.info("%s %s -> %s", self.command, self.path, code)
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
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            return self._send_static("index.html", "text/html; charset=utf-8")
        if path == "/app.js":
            return self._send_static("app.js", "application/javascript; charset=utf-8")
        if path == "/health":
            return self._send(200, {"status": "ok", "version": __version__})
        if path == "/config":
            return self._send(200, {"ready": self._provider_ready()})
        if path == "/caps":
            caps = detect_capabilities()
            payload = caps.to_dict()
            payload["can_run_untrusted"] = caps.can_run_untrusted()
            payload["best_isolation"] = caps.best_isolation()
            return self._send(200, payload)
        if path == "/jobs":
            return self._send(200, {"jobs": self.store.list_summaries()})
        em = _EVENTS_PATH.match(path)
        if em:
            return self._stream_events(em.group(1))
        am = _ARTIFACT_PATH.match(path)
        if am:
            return self._download_artifact(am.group(1))
        jam = _JOB_ARTIFACT_PATH.match(path)
        if jam:
            return self._download_job_artifact(jam.group(1))
        fm = _FILES_PATH.match(path)
        if fm:
            return self._download_output(fm.group(1), fm.group(2))
        pm = _PREVIEW_PATH.match(path)
        if pm:
            return self._serve_preview(pm.group(1), pm.group(2))
        m = _JOB_PATH.match(path)
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
        return self._send(404, {"error": "not found"})

    def do_PUT(self):  # noqa: N802
        # File upload: raw bytes with X-Filename header, streamed to disk.
        if self.path == "/upload":
            return self._upload()
        return self._send(404, {"error": "not found"})

    def do_DELETE(self):  # noqa: N802
        m = _JOB_PATH.match(self.path.split("?", 1)[0])
        if m:
            ok = self.store.delete(m.group(1))
            return self._send(200 if ok else 404,
                              {"deleted": ok, "id": m.group(1)})
        return self._send(404, {"error": "not found"})

    # --- static + streaming ---
    def _send_static(self, name: str, content_type: str) -> None:
        path = _STATIC_DIR / name
        try:
            data = path.read_bytes()
        except OSError:
            return self._send(404, {"error": "UI not found"})
        _log.info("GET %s -> 200 (static)", self.path)
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    @staticmethod
    def _provider_ready() -> bool:
        """True if the server-configured model provider can be constructed
        (its API key is present). Never reveals which provider it is."""
        import os

        from ..agent import get_provider

        name = os.environ.get("REVERSEAI_PROVIDER", "deepseek")
        try:
            get_provider(name)
            return True
        except Exception:
            return False

    def _start_run(self, body) -> None:
        stream_id, conversation_id, error = self.runs.start(body)
        if error:
            return self._send(400, {"error": error})
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
        # Store under a per-upload subdir so the original filename is preserved
        # (and never leaks an id prefix into a delivered artifact's name).
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
        # Identify the uploaded file (format or archive type) for the UI, and —
        # for a reasonably sized binary — a quick arch/bits preview.
        kind, arch, bits = "unknown", None, None
        try:
            from ..core.identify import detect_format
            from ..security.archive import is_archive
            head = dest.open("rb").read(512)
            fmt = detect_format(head)
            kind = fmt.value if fmt.value != "unknown" else (is_archive(head) or "unknown")
            if fmt.value != "unknown" and written <= 256 * 1024 * 1024:
                from ..core import analyze_file
                rep = analyze_file(str(dest))
                arch, bits = rep.arch.value, rep.bits
        except Exception:
            pass
        return self._send(200, {"path": str(dest), "filename": safe,
                                "size": written, "kind": kind,
                                "arch": arch, "bits": bits})

    def _download_artifact(self, cid: str) -> None:
        self._serve_file(self.runs.artifact_path(cid), "no artifact for this conversation")

    def _download_job_artifact(self, job_id: str) -> None:
        p = self.store.artifact_for(job_id)
        self._serve_file(str(p) if p else None, "no artifact for this job")

    def _serve_file(self, path, not_found_msg: str) -> None:
        if not path:
            return self._send(404, {"error": not_found_msg})
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            return self._send(404, {"error": str(exc)})
        # Strip the "<job_id>__" storage prefix from the download name if present.
        name = Path(path).name.split("__", 1)[-1]
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _stream_events(self, job_id: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            for chunk in self.runs.stream(job_id):
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # client disconnected; nothing to do

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

    # --- engine REST endpoints (binary modification / verification / clone) ---

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
        try:
            patches = [
                BytePatch(offset=int(p["offset"]), data=bytes.fromhex(p["hex"]),
                          expected_original=bytes.fromhex(p["expect_hex"]) if p.get("expect_hex") else None)
                for p in patches_in
            ]
        except (KeyError, ValueError) as exc:
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
        report = compare_execution(original, modified, body.get("args", []))
        return self._send(200 if report.ran else 400, report.to_dict())

    def _api_clone(self, body):
        import shutil

        from ..clone import CloneError, clone_site

        url = body.get("url")
        if not url:
            return self._send(400, {"error": "need 'url'"})
        out, token = self._api_out()
        try:
            res = clone_site(url, out / "site",
                             rename_from=body.get("rename_from"),
                             rename_to=body.get("rename_to"))
        except (CloneError, OSError) as exc:
            return self._send(400, {"error": str(exc)})
        zip_path = shutil.make_archive(str(out / "site_clone"), "zip", str(out / "site"))
        d = res.to_dict()
        d["download"] = f"/files/{token}/{Path(zip_path).name}"
        return self._send(200, d)

    def _serve_preview(self, cid: str, relpath: str) -> None:
        """Serve a cloned/built site live so it can render in the preview pane."""
        import mimetypes

        conv = self.runs.conversation(cid)
        if conv is None:
            return self._send(404, {"error": "no such session"})
        base = (Path(conv.workspace) / "clone").resolve()
        if not base.is_dir():
            return self._send(404, {"error": "nothing built to preview yet"})
        rel = relpath or "index.html"
        target = (base / rel).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return self._send(404, {"error": "not found"})
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            return self._send(404, {"error": "not found"})
        try:
            data = target.read_bytes()
        except OSError:
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

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
        runs = RunManager(store)
        handler = type("BoundHandler", (_Handler,), {"store": store, "runs": runs})
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.store = store
        self.runs = runs

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
