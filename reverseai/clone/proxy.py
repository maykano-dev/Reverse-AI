"""A minimal browsing proxy so external sites render inside the preview frame.

Browsers refuse to embed most sites in an iframe (X-Frame-Options /
frame-ancestors). This fetches the top-level document server-side, strips those
headers (we serve our own), injects a <base> so the page's own assets load
directly from the origin, and rewrites links/forms to keep navigation inside the
proxy. Passive sub-resources (CSS/JS/images) load cross-origin fine; only the
top document needs proxying.

SSRF-guarded: http/https only, public hosts only, size-capped, timeouts.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request

from .web import TIMEOUT, _UA, _is_public_host

PROXY_PREFIX = "/proxy?url="
MAX_PROXY_BYTES = 20 * 1024 * 1024


class ProxyError(Exception):
    pass


def fetch(url: str, allow_private: bool = False) -> tuple[bytes, str, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ProxyError("only http/https URLs are supported")
    if not parsed.hostname or (not allow_private and not _is_public_host(parsed.hostname)):
        raise ProxyError("refusing to fetch a non-public host")
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read(MAX_PROXY_BYTES + 1)
            ctype = resp.headers.get("Content-Type", "")
            final_url = resp.geturl()
    except Exception as exc:  # network/HTTP errors -> ProxyError
        raise ProxyError(f"fetch failed: {exc}") from exc
    if len(data) > MAX_PROXY_BYTES:
        raise ProxyError("response too large")
    return data, ctype, final_url  # type: ignore[return-value]


def _proxify(abs_url: str) -> str:
    return PROXY_PREFIX + urllib.parse.quote(abs_url, safe="")


def rewrite_html(html: str, base_url: str) -> str:
    """Make a fetched page browsable inside the proxy frame."""
    # Drop any existing <base> so our injected one wins.
    html = re.sub(r"<base\b[^>]*>", "", html, flags=re.IGNORECASE)

    # 1) Keep navigation inside the proxy: rewrite <a href> and <form action>.
    def _nav(m: re.Match) -> str:
        attr, quote, val = m.group(1), m.group(2), m.group(3)
        if val.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            return m.group(0)
        absolute = urllib.parse.urljoin(base_url, val)
        if not absolute.startswith(("http://", "https://")):
            return m.group(0)
        return f"{attr}={quote}{_proxify(absolute)}{quote}"

    html = re.sub(r'\b(href|action)=(["\'])(.*?)\2', _nav, html, flags=re.IGNORECASE)

    # 2) Inject <base> AFTER link rewriting so it isn't proxified itself; it makes
    #    the page's own assets (css/js/img) load directly from the origin.
    base_tag = f'<base href="{base_url}">'
    if re.search(r"<head[^>]*>", html, re.IGNORECASE):
        html = re.sub(r"(<head[^>]*>)", r"\1" + base_tag, html,
                      count=1, flags=re.IGNORECASE)
    else:
        html = base_tag + html
    return html
