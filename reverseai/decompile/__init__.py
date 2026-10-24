"""Decompilation backends (optional). Ghidra headless today."""

from .ghidra import (
    DecompileResult,
    decompile,
    ghidra_available,
    ghidra_home,
    supported_jdk,
)

__all__ = ["decompile", "ghidra_available", "ghidra_home", "supported_jdk",
           "DecompileResult"]
