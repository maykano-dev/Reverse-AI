"""Web research: search, fetch, clean, and cite.

This is the "read the web and show your sources" capability that personal
agents ship. It is deliberately small and dependency-free:

  * ``search_web`` uses a SearXNG-compatible JSON endpoint when configured
    (``REVERSEAI_SEARCH_URL``), otherwise DuckDuckGo's HTML endpoint.
  * ``read_page`` fetches a public page, validates every redirect, strips
    scripts/styles, and returns readable text plus title/description.
  * Every fetch is SSRF-guarded: http(s) only, public hosts only, bounded bytes,
    bounded redirects, and timeouts.

The tools that use this module append sources to the job so the UI can render
Source cards and the answer can cite real URLs.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any

from ..security.net import NetworkError, fetch as safe_fetch, is_public_host

_UA = "Mozilla/5.0 (compatible; ReverseAI-Research/1.0)"
_TIMEOUT = 15.0
_MAX_BYTES = 3 * 1024 * 1024


class ResearchError(Exception):
    pass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = "web"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Page:
    url: str
    title: str = ""
    description: str = ""
    text: str = ""
    links: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"url": self.url, "title": self.title,
                "description": self.description, "chars": len(self.text)}


# ---------------------------------------------------------------------------
# SSRF-safe fetching
# ---------------------------------------------------------------------------

def fetch_bytes(url: str, max_bytes: int = _MAX_BYTES,
                allow_private: bool = False) -> tuple[bytes, str, str]:
    """Fetch a public URL, validating every redirect hop. Returns (bytes, ctype, final)."""
    try:
        return safe_fetch(
            url, max_bytes=max_bytes, allow_private=allow_private,
            timeout=_TIMEOUT, user_agent=_UA,
            accept="text/html,application/xhtml+xml,application/json;q=0.8,*/*;q=0.5")
    except NetworkError as exc:
        raise ResearchError(str(exc)) from exc


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

class _PageParser(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self._in_title = False
        self._skip_depth = 0
        self._chunks: list[str] = []
        self.links: list[str] = []
        self._base = ""

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        elif tag == "meta" and (d.get("name", "").lower() in ("description", "og:description")):
            self.description = (d.get("content") or "").strip()
        elif tag == "base" and d.get("href"):
            self._base = d["href"]
        elif tag == "a" and d.get("href"):
            self.links.append(d["href"])
        if tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4",
                   "section", "article", "header", "footer", "pre", "blockquote"):
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._in_title = False
        if tag in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section",
                   "article", "header", "footer", "pre", "blockquote"):
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        else:
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        raw = html.unescape(raw)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*\n+", "\n\n", raw)
        return raw.strip()


def parse_page(data: bytes | str, url: str = "") -> Page:
    if isinstance(data, bytes):
        # Try UTF-8, then a permissive fallback. Real pages are messy.
        text = data.decode("utf-8", "replace")
    else:
        text = data
    parser = _PageParser()
    try:
        parser.feed(text)
    except Exception:
        pass
    title = re.sub(r"\s+", " ", parser.title).strip()
    description = re.sub(r"\s+", " ", parser.description).strip()
    base = parser._base or url
    links: list[str] = []
    for href in parser.links:
        if href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urllib.parse.urljoin(base, href)
        if absolute.startswith(("http://", "https://")) and absolute not in links:
            links.append(absolute)
    return Page(url=url, title=title, description=description,
                text=parser.text(), links=links[:80])


class _SearchParser(HTMLParser):
    """Collect DuckDuckGo result anchors and snippets in document order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self._mode: str | None = None
        self._buf: list[str] = []
        self._href = ""

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        d = dict(attrs)
        cls = (d.get("class") or "").lower()
        if "result__a" in cls:
            self._mode, self._buf = "title", []
            self._href = d.get("href") or ""
        elif "result__snippet" in cls:
            self._mode, self._buf = "snippet", []

    def handle_endtag(self, tag):
        if tag == "a" and self._mode:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if self._mode == "title" and text:
                self.items.append({"title": text, "url": self._href, "snippet": ""})
            elif self._mode == "snippet" and self.items and not self.items[-1]["snippet"]:
                self.items[-1]["snippet"] = text
            self._mode = None

    def handle_data(self, data):
        if self._mode:
            self._buf.append(data)


def _decode_ddg(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        q = urllib.parse.parse_qs(parsed.query)
        if q.get("uddg"):
            return q["uddg"][0]
    return url


def parse_search_results(data: bytes | str, base: str = "https://duckduckgo.com") -> list[SearchResult]:
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    parser = _SearchParser()
    try:
        parser.feed(text)
    except Exception:
        pass
    out: list[SearchResult] = []
    seen: set[str] = set()
    for item in parser.items:
        url = _decode_ddg(urllib.parse.urljoin(base, item["url"]))
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append(SearchResult(item["title"], url, item.get("snippet", "")))
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_web(query: str, max_results: int = 5) -> list[SearchResult]:
    query = (query or "").strip()
    if not query:
        raise ResearchError("empty search query")
    max_results = max(1, min(int(max_results or 5), 10))

    import os

    searx = os.environ.get("REVERSEAI_SEARCH_URL")
    if searx:
        sep = "&" if "?" in searx else "?"
        url = f"{searx}{sep}q={urllib.parse.quote(query)}&format=json"
        data, _ctype, _final = fetch_bytes(url, max_bytes=1_000_000)
        try:
            payload = json.loads(data.decode("utf-8", "replace"))
        except json.JSONDecodeError as exc:
            raise ResearchError("search endpoint did not return JSON") from exc
        rows = payload.get("results") or []
        return [SearchResult(str(r.get("title", "")), str(r.get("url", "")),
                             str(r.get("content", ""))) for r in rows[:max_results]
                if r.get("url")]

    errors: list[str] = []
    for endpoint in ("https://html.duckduckgo.com/html/",
                     "https://lite.duckduckgo.com/lite/"):
        try:
            url = endpoint + "?" + urllib.parse.urlencode({"q": query})
            data, _ctype, final = fetch_bytes(url, max_bytes=1_500_000)
            results = parse_search_results(data, final)[:max_results]
            if results:
                return results
            errors.append(f"{endpoint}: no results")
        except ResearchError as exc:
            errors.append(f"{endpoint}: {exc}")
    raise ResearchError("search failed (" + "; ".join(errors) + ")")


def read_page(url: str, max_chars: int = 20000) -> Page:
    data, ctype, final = fetch_bytes(url)
    if "application/json" in ctype.lower():
        try:
            payload = json.loads(data.decode("utf-8", "replace"))
            text = json.dumps(payload, indent=2)[:max_chars]
            return Page(url=final, title=urllib.parse.urlparse(final).hostname or final,
                        text=text)
        except json.JSONDecodeError:
            pass
    page = parse_page(data, final)
    if len(page.text) > max_chars:
        page.text = page.text[:max_chars].rsplit(" ", 1)[0] + " …"
    if not page.title:
        page.title = urllib.parse.urlparse(final).hostname or final
    return page


def source_card(url: str, title: str = "", snippet: str = "") -> dict[str, Any]:
    return {
        "url": url,
        "title": title or urllib.parse.urlparse(url).hostname or url,
        "snippet": snippet[:280],
    }
