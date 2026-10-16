"""Reconstruction engine — rebuild things ReverseAI is shown.

Today: static website cloning (fetch a page + its assets and produce a working
local replica, optionally renamed). This is a best-effort *frontend* clone —
exact HTML/CSS/JS and animations, not the server behind them.
"""

from .web import CloneError, CloneResult, clone_site

__all__ = ["clone_site", "CloneResult", "CloneError"]
