"""Reconstruction engine — rebuild things ReverseAI is shown.

Today: static website cloning (fetch a page + its assets and produce a working
local replica, optionally renamed). This is a best-effort *frontend* clone —
exact HTML/CSS/JS and animations, not the server behind them.
"""

from .web import CloneError, CloneResult, clone_site


def clone_best(url, out_dir, rename_from=None, rename_to=None, allow_private=False):
    """Clone with the best available engine: a headless browser when Chromium is
    installed (renders JS, captures real assets), otherwise a static fetch.

    Rendering is opt-in on servers (``REVERSEAI_ALLOW_BROWSER_RENDER=1``) because
    a headless browser parsing an untrusted page is itself an attack surface.
    """
    import os

    from .render import chromium_ready, render_and_capture

    if os.environ.get("REVERSEAI_ALLOW_BROWSER_RENDER") == "1" and chromium_ready():
        try:
            res = render_and_capture(url, out_dir, rename_from, rename_to,
                                     allow_private=allow_private)
            res.engine = "rendered"
            return res
        except Exception:
            pass  # fall back to static
    res = clone_site(url, out_dir, rename_from, rename_to, allow_private=allow_private)
    res.engine = "static"
    return res


__all__ = ["clone_site", "clone_best", "CloneResult", "CloneError"]
