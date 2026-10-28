"""Persistent local preview servers, behind an explicit operator gate.

The preview browser can show static files by itself. Framework projects need a
long-running dev server. This module runs the user's command inside bubblewrap:
the workspace is writable, the host system is read-only, capabilities are
dropped, and the process dies with the app. Network is shared because a dev
server must bind a loopback port; the command is still confined to the sandbox
for filesystem and process access.

Disabled unless ``REVERSEAI_ALLOW_PREVIEW_SERVER=1``. The API never starts a
command on the host when bubblewrap is unavailable.
"""

from __future__ import annotations

import os
import queue
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..sandbox import seccomp
from ..sandbox.backends.bubblewrap import BubblewrapSandbox
from ..sandbox.policy import SandboxPolicy


class PreviewServerError(Exception):
    pass


@dataclass
class PreviewProcess:
    cid: str
    port: int
    argv: list[str]
    process: subprocess.Popen
    log_path: str
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conversation_id": self.cid,
            "port": self.port,
            "url": f"http://127.0.0.1:{self.port}/",
            "command": self.argv,
            "pid": self.process.pid,
            "running": self.process.poll() is None,
            "started_at": self.started_at,
            "log": self.log_path,
        }


class PreviewServerManager:
    def __init__(self) -> None:
        self._servers: dict[str, PreviewProcess] = {}

    @staticmethod
    def enabled() -> bool:
        return os.environ.get("REVERSEAI_ALLOW_PREVIEW_SERVER") == "1"

    def status(self, cid: str) -> dict[str, Any]:
        proc = self._servers.get(cid)
        if proc is None:
            return {"running": False, "enabled": self.enabled()}
        alive = proc.process.poll() is None
        if not alive:
            self._servers.pop(cid, None)
            return {"running": False, "enabled": self.enabled()}
        return {**proc.to_dict(), "enabled": True}

    def start(self, cid: str, workspace: str, command: str | list[str],
              port: int) -> dict[str, Any]:
        if not self.enabled():
            raise PreviewServerError(
                "the dev-server preview is disabled. Set "
                "REVERSEAI_ALLOW_PREVIEW_SERVER=1 on the server to enable it.")
        if not BubblewrapSandbox.is_available():
            raise PreviewServerError(
                "bubblewrap/user namespaces are unavailable; refusing to run a "
                "project command on the host")
        if not (1024 <= int(port) <= 65535):
            raise PreviewServerError("port must be between 1024 and 65535")
        argv = self._argv(command, int(port))
        if not argv:
            raise PreviewServerError("command is empty")
        self.stop(cid)
        root = Path(workspace).resolve()
        if not root.is_dir():
            raise PreviewServerError("workspace does not exist")
        if not self._port_free(int(port)):
            raise PreviewServerError(f"port {port} is already in use")
        log_dir = root / ".reverseai"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / "preview-server.log"
        bpf_path = None
        bpf_fd = None
        log_fh = None
        scratch = None
        try:
            if seccomp.available():
                bpf_path, bpf_fd = seccomp.write_bpf()
            policy = SandboxPolicy(
                allow_network=True,
                workdir=str(root),
                rw_binds=[str(root)],
                allow_untrusted_execution=True,
                env={
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "HOME": str(root),
                    "HOST": "127.0.0.1",
                    "PORT": str(port),
                    "LANG": "C.UTF-8",
                    "TERM": "dumb",
                    "BROWSER": "none",
                },
            )
            bw = BubblewrapSandbox()
            scratch = tempfile.mkdtemp(prefix="reverseai-preview-")
            if scratch is None:
                raise PreviewServerError("could not create a sandbox scratch dir")
            args = bw._build_args(bw._bwrap(), policy, scratch, bpf_fd)
            full = args + ["--"] + argv
            log_fh = log_path.open("ab")
            result: queue.Queue = queue.Queue(maxsize=1)

            def _launch() -> None:
                # Keep this thread alive for the child's lifetime. bwrap's
                # --die-with-parent is tied to the parent *thread*; launching
                # from an HTTP handler thread would kill the server as soon as
                # the request ended.
                try:
                    proc = subprocess.Popen(
                        full,
                        stdin=subprocess.DEVNULL,
                        stdout=log_fh,
                        stderr=subprocess.STDOUT,
                        close_fds=True,
                        pass_fds=(bpf_fd,) if bpf_fd is not None else (),
                        start_new_session=True,
                    )
                    result.put(("ok", proc))
                    proc.wait()
                except Exception as exc:  # pragma: no cover - host error
                    result.put(("err", exc))

            threading.Thread(target=_launch, daemon=True,
                             name=f"preview-{cid}").start()
            kind, value = result.get(timeout=10)
            if kind == "err":
                raise PreviewServerError(f"could not launch server: {value}")
            proc = value
            self._servers[cid] = PreviewProcess(
                cid, int(port), argv, proc, str(log_path))
            deadline = time.monotonic() + float(
                os.environ.get("REVERSEAI_PREVIEW_START_TIMEOUT", "15") or 15)
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    tail = self._tail(log_path)
                    self.stop(cid)
                    raise PreviewServerError(
                        f"server exited during startup (code {proc.returncode}). "
                        f"Log: {tail or '(empty)'}")
                if self._port_open(int(port)):
                    return self.status(cid)
                time.sleep(0.25)
            self.stop(cid)
            raise PreviewServerError(
                f"server did not open 127.0.0.1:{port} in time. "
                f"Log: {self._tail(log_path) or '(empty)'}")
        except PreviewServerError:
            raise
        except OSError as exc:
            raise PreviewServerError(f"could not start preview server: {exc}") from exc
        finally:
            if log_fh is not None:
                try:
                    log_fh.close()
                except OSError:
                    pass
            if bpf_fd is not None:
                try:
                    os.close(bpf_fd)
                except OSError:
                    pass
            if bpf_path:
                try:
                    os.unlink(bpf_path)
                except OSError:
                    pass
            if scratch:
                shutil.rmtree(scratch, ignore_errors=True)

    def stop(self, cid: str) -> bool:
        proc = self._servers.pop(cid, None)
        if proc is None:
            return False
        p = proc.process
        if p.poll() is not None:
            return False
        for sig, wait in ((signal.SIGTERM, 4.0), (signal.SIGKILL, 2.0)):
            try:
                os.killpg(p.pid, sig)
            except OSError:
                try:
                    p.send_signal(sig)
                except OSError:
                    pass
            try:
                p.wait(timeout=wait)
                return True
            except subprocess.TimeoutExpired:
                continue
        return False

    def stop_all(self) -> None:
        for cid in list(self._servers):
            self.stop(cid)

    @staticmethod
    def _argv(command: str | list[str], port: int) -> list[str]:
        if isinstance(command, str):
            argv = shlex.split(command)
        elif isinstance(command, list):
            argv = [str(x) for x in command]
        else:
            raise PreviewServerError("command must be a string or argv list")
        argv = [x.replace("{port}", str(port)) for x in argv[:64] if str(x)]
        if any(len(x) > 4096 for x in argv):
            raise PreviewServerError("command argument is too long")
        return argv

    @staticmethod
    def _port_free(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return True
            except OSError:
                return False

    @staticmethod
    def _port_open(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            return False

    @staticmethod
    def _tail(path: Path, limit: int = 1600) -> str:
        try:
            data = path.read_bytes()
        except OSError:
            return ""
        return data[-limit:].decode("utf-8", "replace").strip()
