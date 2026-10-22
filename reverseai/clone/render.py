"""Headless-browser rendering (Playwright/Chromium), optional.

Unlike the static fetch, this actually *renders* a page — running its
JavaScript — and captures the fully-rendered DOM plus every resource the browser
loaded (CSS, JS, fonts, images). That makes faithful clones of real, JS-driven
sites possible, and lets the preview show live pages. Degrades cleanly when
Playwright/Chromium is not installed.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from .web import CloneResult, _asset_name, _rename, _is_public_host
import urllib.parse


def playwright_available() -> bool:
    if importlib.util.find_spec("playwright") is None:
        return False
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401

        return True
    except Exception:
        return False


def chromium_ready() -> bool:
    """True only if the Chromium binary is actually installed."""
    if not playwright_available():
        return False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
            return bool(path) and Path(path).exists()
    except Exception:
        return False


def render_and_capture(
    url: str,
    out_dir: str | Path,
    rename_from: str | None = None,
    rename_to: str | None = None,
    timeout_ms: int = 35000,
    allow_private: bool = False,
) -> CloneResult:
    """Render ``url`` in a headless browser and save a self-contained copy."""
    from playwright.sync_api import sync_playwright

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise RuntimeError("only http/https URLs are supported")
    if not parsed.hostname or (not allow_private and not _is_public_host(parsed.hostname)):
        raise RuntimeError("refusing to render a non-public host")

    out = Path(out_dir)
    adir = out / "assets"
    adir.mkdir(parents=True, exist_ok=True)
    result = CloneResult(out_dir=str(out))
    saved: dict[str, str] = {}   # absolute url -> "assets/NAME"
    css_files: list[Path] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1366, "height": 900})

        def _on_response(resp):
            try:
                u = resp.url
                if u == url or u.startswith("data:") or u in saved:
                    return
                ct = (resp.headers or {}).get("content-type", "").lower()
                if not any(k in ct for k in ("css", "javascript", "image", "font",
                                             "octet-stream", "json", "svg")):
                    return
                body = resp.body()
                if not body or len(body) > 15 * 1024 * 1024:
                    return
                name = _asset_name(u, len(saved))
                dest = adir / name
                dest.write_bytes(body)
                saved[u] = f"assets/{name}"
                if "css" in ct or u.split("?")[0].lower().endswith(".css"):
                    css_files.append(dest)
                result.assets += 1
                result.total_bytes += len(body)
            except Exception:
                pass

        page.on("response", _on_response)
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except Exception:
            # networkidle can time out on chatty pages; take what rendered so far.
            try:
                page.wait_for_timeout(1500)
            except Exception:
                pass
        html = page.content()
        browser.close()

    # Rewrite captured CSS so url()/@import point at the sibling local copies.
    for css_path in css_files:
        try:
            text = css_path.read_text("utf-8", "replace")
            for u, local in saved.items():
                text = text.replace(u, Path(local).name)
            css_path.write_text(text, "utf-8")
        except OSError:
            pass

    # Localise absolute asset URLs in the rendered HTML; a <base> covers the rest.
    for u, local in saved.items():
        html = html.replace(u, local)
    base_tag = f'<base href="{url}">'
    if "<head" in html.lower():
        import re
        html = re.sub(r"(<head[^>]*>)", r"\1" + base_tag, html, count=1, flags=re.IGNORECASE)
    else:
        html = base_tag + html

    if rename_from and rename_to:
        html, n = _rename(html, rename_from, rename_to)
        result.renamed = n

    (out / "index.html").write_text(html, "utf-8")
    return result


def screenshot(url: str, out_path: str | Path, full_page: bool = True,
               timeout_ms: int = 30000) -> str:
    """Render a page and save a PNG screenshot (for previews/evidence)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1366, "height": 900})
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except Exception:
            pass
        page.screenshot(path=str(out_path), full_page=full_page)
        browser.close()
    return str(out_path)
