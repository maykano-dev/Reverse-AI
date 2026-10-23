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


def ghidra_available() -> bool:
    return ghidra_home() is not None


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
        cmd = [
            headless, proj, "rvai",
            "-import", binary_path,
            "-scriptPath", str(_SCRIPT),
            "-postScript", "decompile_export.py",
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
