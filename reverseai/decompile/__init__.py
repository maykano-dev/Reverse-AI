"""Decompilation backends (optional). Ghidra headless today."""

from .ghidra import DecompileResult, decompile, ghidra_available, ghidra_home

__all__ = ["decompile", "ghidra_available", "ghidra_home", "DecompileResult"]
