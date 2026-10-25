"""Ghidra headless decompilation (optional).

Feeds the agent real decompiled C — far more useful than disassembly — by
running Ghidra's analyzeHeadless on the target with an export script. Ghidra
only *statically* analyzes the binary (it never runs it), so this is safe on the
host, like objdump. Degrades cleanly when Ghidra is not installed.

Set REVERSEAI_GHIDRA to the Ghidra install dir, or drop it in ~/ghidra.
"""

from __future__ import annotations

import glob
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_SCRIPT = Path(__file__).parent / "scripts"


def ghidra_home() -> str | None:
    env = os.environ.get("REVERSEAI_GHIDRA")
    candidates = []
    if env:
        candidates.append(env)
    candidates += sorted(glob.glob(os.path.expanduser("~/ghidra/ghidra_*_PUBLIC")), reverse=True)
    candidates += sorted(glob.glob("/opt/ghidra*"), reverse=True)
    for c in candidates:
        if c and Path(c, "support", "analyzeHeadless").exists():
            return c
    return None


def _ghidra_java_range(home: str | None) -> tuple[int, int | None]:
    """Read the JDK major-version range this Ghidra build requires.

    Ghidra records it in Ghidra/application.properties (application.java.min /
    application.java.max). Different releases need very different JDKs — e.g.
    Ghidra 11.x wants 17-21, Ghidra 12.2 wants 25+ — so we never hardcode it.
    Falls back to a permissive 17+ when the file can't be read.
    """
    lo: int = 17
    hi: int | None = None
    if home:
        props = Path(home) / "Ghidra" / "application.properties"
        try:
            for line in props.read_text("utf-8", "replace").splitlines():
                key, _, val = line.partition("=")
                val = val.strip()
                if not val:
                    continue
                if key.strip() == "application.java.min":
                    lo = int(val)
                elif key.strip() == "application.java.max":
                    hi = int(val)
        except (OSError, ValueError):
            pass
    return lo, hi


def _java_major(java: Path) -> int | None:
    try:
        out = subprocess.run([str(java), "-version"], capture_output=True,
                             text=True, timeout=10).stderr
    except (OSError, subprocess.SubprocessError):
        return None
    import re
    m = re.search(r'version "(\d+)', out)
    return int(m.group(1)) if m else None


def supported_jdk() -> str | None:
    """Find a JDK whose major version satisfies this Ghidra build's requirement.

    Checks REVERSEAI_JDK, any portable ~/jdk*/jdk-*, and the system JVMs in
    /usr/lib/jvm. Returns the JAVA_HOME to force, or None when the host's own
    default java already fits (so no override is needed).
    """
    home = ghidra_home()
    lo, hi = _ghidra_java_range(home)

    candidates = []
    env = os.environ.get("REVERSEAI_JDK")
    if env:
        candidates.append(env)
    candidates += sorted(glob.glob(os.path.expanduser("~/jdk*/jdk-*")), reverse=True)
    candidates += sorted(glob.glob("/usr/lib/jvm/*"), reverse=True)
    for cand in candidates:
        java = Path(cand) / "bin" / "java"
        # Ghidra's headless analyzer needs a full JDK (it compiles), not a JRE,
        # so require javac too. A JRE-only install (common on servers) won't do.
        if not java.exists() or not (Path(cand) / "bin" / "javac").exists():
            continue
        major = _java_major(java)
        if major is not None and major >= lo and (hi is None or major <= hi):
            return str(cand)
    return None


def ghidra_available() -> bool:
    return ghidra_home() is not None and supported_jdk() is not None


def _persist_jdk(home: str, jdk: str) -> None:
    """Record the chosen JDK in Ghidra's own saved-JDK config.

    Ghidra's launcher rejects a JDK passed through the JAVA_HOME *environment*
    variable when its version string has four parts (e.g. "25.0.4.1"), but it
    happily reads the very same path from its java_home.save file. So we write
    the save file and leave JAVA_HOME alone. Best-effort; failure just means
    Ghidra auto-detects on its own.
    """
    try:
        cfg = Path.home() / ".config" / "ghidra" / Path(home).name
        cfg.mkdir(parents=True, exist_ok=True)
        # analyzeHeadless uses -jdk_home (jdk_home.save); GUI uses -java_home.
        # Write both so either launcher finds it.
        (cfg / "jdk_home.save").write_text(jdk + "\n", "utf-8")
        (cfg / "java_home.save").write_text(jdk + "\n", "utf-8")
    except OSError:
        pass


@dataclass
class DecompileResult:
    ok: bool
    code: str = ""
    functions: int = 0
    error: str | None = None
    log: str = ""

    def to_dict(self):
        return {"ok": self.ok, "functions": self.functions,
                "chars": len(self.code), "error": self.error}


def decompile(binary_path: str, max_functions: int = 400,
              timeout: int = 420) -> DecompileResult:
    home = ghidra_home()
    if home is None:
        return DecompileResult(False, error="Ghidra not installed")
    headless = str(Path(home) / "support" / "analyzeHeadless")

    with tempfile.TemporaryDirectory(prefix="rvai-ghidra-") as proj:
        out_file = Path(proj) / "decomp.c"
        env = dict(os.environ)
        env["REVERSEAI_DECOMP_OUT"] = str(out_file)
        env["REVERSEAI_DECOMP_MAX"] = str(max_functions)
        jdk = supported_jdk()
        if jdk:
            _persist_jdk(home, jdk)
        # Don't pass JAVA_HOME through: Ghidra's env-var validation rejects some
        # valid JDKs (four-part versions). The saved config above handles it;
        # removing a host-set JAVA_HOME avoids the same rejection on its value.
        env.pop("JAVA_HOME", None)
        cmd = [
            headless, proj, "rvai",
            "-import", binary_path,
            "-scriptPath", str(_SCRIPT),
            "-postScript", "decompile_export.java",
            "-deleteProject",
            "-analysisTimeoutPerFile", str(max(timeout - 30, 60)),
        ]
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True,
                                  timeout=timeout)
        except subprocess.TimeoutExpired:
            if out_file.exists():
                return _read(out_file, "(decompilation timed out; partial result)")
            return DecompileResult(False, error="decompilation timed out")
        except OSError as exc:
            return DecompileResult(False, error=f"failed to launch Ghidra: {exc}")

        if out_file.exists():
            return _read(out_file, proc.stdout[-2000:])
        return DecompileResult(False, error="no decompiler output",
                               log=(proc.stderr or proc.stdout)[-2000:])


def _read(out_file: Path, log: str) -> DecompileResult:
    code = out_file.read_text("utf-8", "replace")
    n = code.count("// --- ")
    return DecompileResult(True, code=code, functions=n, log=log)
