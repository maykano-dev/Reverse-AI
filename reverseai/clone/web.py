"""Static website cloning.

Fetch a page and its same-origin assets (CSS, JS, images, fonts), rewrite
references to local copies, optionally rename a brand throughout, and write a
self-contained folder that renders offline. This reproduces the exact front-end
— markup, styling, and CSS/JS animations — but not the server behind it.

Safety: only http/https; blocks requests to private/loopback/link-local hosts
(SSRF guard); bounds the number and total size of assets and uses timeouts.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ..security.validate import safe_join

_UA = "Mozilla/5.0 (compatible; ReverseAI-Clone/1.0)"
MAX_ASSETS = 80
MAX_ASSET_BYTES = 15 * 1024 * 1024
MAX_HTML_BYTES = 10 * 1024 * 1024
TIMEOUT = 15.0

# Attributes that reference a fetchable asset, by tag.
_ASSET_ATTRS = {
    "link": "href", "script": "src", "img": "src", "source": "src",
    "video": "src", "audio": "src",
}


class CloneError(Exception):
    pass


@dataclass
class CloneResult:
    out_dir: str
    pages: int = 1
    assets: int = 0
    total_bytes: int = 0
    renamed: int = 0
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"out_dir": self.out_dir, "pages": self.pages, "assets": self.assets,
                "total_bytes": self.total_bytes, "renamed": self.renamed,
                "skipped": self.skipped[:50]}


class _AssetCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.assets: list[str] = []

    def handle_starttag(self, tag, attrs):
        attr = _ASSET_ATTRS.get(tag)
        if not attr:
            return
        d = dict(attrs)
        val = d.get(attr)
        # Only stylesheets/icons for <link>, to avoid preconnect/alternate noise.
        if tag == "link":
            rel = (d.get("rel") or "").lower()
            if not any(k in rel for k in ("stylesheet", "icon", "preload")):
                return
        if val and not val.startswith(("data:", "javascript:", "#", "mailto:")):
            self.assets.append(val)


def _is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast):
            return False
    return True


def _fetch(url: str, limit: int, allow_private: bool = False) -> tuple[bytes, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise CloneError(f"unsupported scheme: {parsed.scheme}")
    if not parsed.hostname or (not allow_private and not _is_public_host(parsed.hostname)):
        raise CloneError(f"refusing to fetch non-public host: {parsed.hostname}")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = resp.read(limit + 1)
        if len(data) > limit:
            raise CloneError(f"resource exceeds {limit} bytes: {url}")
        ctype = resp.headers.get("Content-Type", "")
    return data, ctype


def _asset_name(url: str, index: int) -> str:
    path = urllib.parse.urlparse(url).path
    base = Path(path).name or f"asset{index}"
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)[:80]
    return f"{index:03d}_{base}"


def clone_site(
    url: str,
    out_dir: str | Path,
    rename_from: str | None = None,
    rename_to: str | None = None,
    max_assets: int = MAX_ASSETS,
    allow_private: bool = False,
) -> CloneResult:
    """Clone ``url`` into ``out_dir`` and (optionally) rename a brand."""
    out = Path(out_dir)
    assets_dir = out / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    html_bytes, _ = _fetch(url, MAX_HTML_BYTES, allow_private)
    html = html_bytes.decode("utf-8", "replace")

    collector = _AssetCollector()
    try:
        collector.feed(html)
    except Exception:
        pass  # best-effort parse

    result = CloneResult(out_dir=str(out))
    seen: dict[str, str] = {}
    for i, ref in enumerate(dict.fromkeys(collector.assets)):
        if result.assets >= max_assets:
            result.skipped.append(f"(asset cap {max_assets} reached)")
            break
        abs_url = urllib.parse.urljoin(url, ref)
        host = urllib.parse.urlparse(abs_url).hostname
        origin_host = urllib.parse.urlparse(url).hostname
        if host != origin_host:
            result.skipped.append(ref)  # off-site asset left as absolute URL
            continue
        try:
            data, _ctype = _fetch(abs_url, MAX_ASSET_BYTES, allow_private)
        except (CloneError, OSError):
            result.skipped.append(ref)
            continue
        name = _asset_name(abs_url, i)
        local = f"assets/{name}"
        # Stylesheets: pull in and localise what they reference (fonts, bg
        # images, @imports) so the actual design renders, not just the markup.
        if _looks_like_css(ref, _ctype):
            try:
                data = _process_css(data.decode("utf-8", "replace"), abs_url,
                                    assets_dir, origin_host, allow_private,
                                    result, max_assets).encode("utf-8")
            except Exception:
                pass
        dest = safe_join(assets_dir, name)
        dest.write_bytes(data)
        seen[ref] = local
        result.assets += 1
        result.total_bytes += len(data)

    # Rewrite asset references in the HTML to the local copies.
    for ref, local in seen.items():
        html = html.replace(f'"{ref}"', f'"{local}"').replace(f"'{ref}'", f"'{local}'")

    # Brand rename (case-insensitive, preserving simple capitalisation).
    if rename_from and rename_to:
        html, n = _rename(html, rename_from, rename_to)
        result.renamed = n

    (out / "index.html").write_text(html, "utf-8")
    return result


def _looks_like_css(ref: str, ctype: str) -> bool:
    return ref.lower().split("?")[0].endswith(".css") or "text/css" in (ctype or "").lower()


_CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""", re.IGNORECASE)
_CSS_IMPORT = re.compile(r"""@import\s+(?:url\()?\s*(['"])([^'"]+)\1""", re.IGNORECASE)


def _process_css(css: str, css_url: str, assets_dir: Path, origin_host: str,
                 allow_private: bool, result: "CloneResult", max_assets: int) -> str:
    """Download same-origin url()/@import targets in a stylesheet and localise them."""
    local_map: dict[str, str] = {}

    def _grab(ref: str) -> str | None:
        ref = ref.strip()
        if ref.startswith(("data:", "#")):
            return None
        abs_url = urllib.parse.urljoin(css_url, ref)
        if urllib.parse.urlparse(abs_url).hostname != origin_host:
            return None
        if ref in local_map:
            return local_map[ref]
        if result.assets >= max_assets:
            return None
        try:
            data, _ct = _fetch(abs_url, MAX_ASSET_BYTES, allow_private)
        except (CloneError, OSError):
            return None
        name = _asset_name(abs_url, 1000 + result.assets)
        safe_join(assets_dir, name).write_bytes(data)
        result.assets += 1
        result.total_bytes += len(data)
        # CSS assets live in assets/, so sibling references are just the name.
        local_map[ref] = name
        return name

    def _sub_url(m: re.Match) -> str:
        local = _grab(m.group(2))
        return f"url({m.group(1)}{local}{m.group(1)})" if local else m.group(0)

    def _sub_import(m: re.Match) -> str:
        local = _grab(m.group(2))
        return f'@import "{local}"' if local else m.group(0)

    css = _CSS_IMPORT.sub(_sub_import, css)
    css = _CSS_URL.sub(_sub_url, css)
    return css


def _rename(text: str, frm: str, to: str) -> tuple[str, int]:
    pattern = re.compile(re.escape(frm), re.IGNORECASE)

    def repl(m: re.Match) -> str:
        s = m.group(0)
        if s.isupper():
            return to.upper()
        if s[0].isupper():
            return to[:1].upper() + to[1:]
        return to.lower()

    new, n = pattern.subn(repl, text)
    return new, n
