"""LIEF-backed structural modifications (EXPERIMENTAL, optional).

Where byte-patching changes existing bytes in place, LIEF can perform
format-aware structural edits — adding an imported library/function or a new
section and re-serializing a valid binary. This is a step toward *adding*
capability, not just tweaking it.

LIEF is an optional dependency. Every entry point degrades cleanly when it is
absent (raises LiefUnavailable), and all output goes to a copy in the job
workspace — the original is never touched.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from ..security.validate import safe_join


class LiefUnavailable(RuntimeError):
    pass


class LiefOpError(RuntimeError):
    pass


def lief_available() -> bool:
    try:
        return importlib.util.find_spec("lief") is not None
    except (ImportError, ValueError):
        return False


def _require_lief():
    if not lief_available():
        raise LiefUnavailable("LIEF not installed (pip install lief)")
    import lief  # type: ignore

    return lief


def add_imported_library(src_path: str, out_dir: str, library: str,
                         functions: list[str] | None = None,
                         out_name: str | None = None) -> str:
    """Add an imported library (and optional functions) to a PE binary."""
    lief = _require_lief()
    try:
        binary = lief.parse(str(src_path))
        if binary is None:
            raise LiefOpError("LIEF could not parse the target")
        lib = binary.add_library(library)
        for fn in functions or []:
            lib.add_entry(fn)
        out = safe_join(out_dir, out_name or (Path(src_path).name + ".imp"))
        out.parent.mkdir(parents=True, exist_ok=True)
        binary.write(str(out))
        return str(out)
    except LiefOpError:
        raise
    except Exception as exc:  # LIEF raises various types
        raise LiefOpError(f"add_imported_library failed: {exc}") from exc


def add_section(src_path: str, out_dir: str, name: str, content: bytes,
                out_name: str | None = None) -> str:
    """Add a new named section containing ``content`` and re-serialize."""
    lief = _require_lief()
    try:
        binary = lief.parse(str(src_path))
        if binary is None:
            raise LiefOpError("LIEF could not parse the target")
        fmt = binary.format
        if fmt == lief.Binary.FORMATS.ELF:
            section = lief.ELF.Section(name)
            section.content = list(content)
        elif fmt == lief.Binary.FORMATS.PE:
            section = lief.PE.Section(name)
            section.content = list(content)
        else:
            raise LiefOpError(f"unsupported format for add_section: {fmt}")
        binary.add(section)
        out = safe_join(out_dir, out_name or (Path(src_path).name + ".sect"))
        out.parent.mkdir(parents=True, exist_ok=True)
        binary.write(str(out))
        return str(out)
    except LiefOpError:
        raise
    except Exception as exc:
        raise LiefOpError(f"add_section failed: {exc}") from exc
