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
class ImageResult:
    title: str
    image_url: str
    page_url: str = ""
    thumbnail: str = ""
    snippet: str = ""
    source: str = "web"
    creator: str = ""
    license: str = ""
    width: int = 0
    height: int = 0

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


class _ImageParser(HTMLParser):
    """Collect images and their useful metadata from a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[dict[str, str]] = []
        self._base = ""

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == "base" and d.get("href"):
            self._base = d["href"]
            return
        if tag == "meta":
            prop = (d.get("property") or d.get("name") or "").lower()
            if prop in ("og:image", "og:image:url", "twitter:image", "twitter:image:src"):
                if d.get("content"):
                    self.images.append({"src": d["content"], "alt": ""})
            return
        if tag == "link" and "image_src" in (d.get("rel") or "").lower():
            if d.get("href"):
                self.images.append({"src": d["href"], "alt": ""})
            return
        if tag == "img":
            src = d.get("src") or d.get("data-src") or ""
            srcset = d.get("srcset") or d.get("data-srcset") or ""
            if srcset:
                parts = []
                for piece in srcset.split(","):
                    bits = piece.strip().split()
                    if not bits:
                        continue
                    try:
                        width = int(bits[1].rstrip("w")) if len(bits) > 1 and bits[1].endswith("w") else 0
                    except ValueError:
                        width = 0
                    parts.append((width, bits[0]))
                if parts:
                    src = max(parts, key=lambda x: x[0])[1]
            if src:
                self.images.append({"src": src, "alt": d.get("alt") or ""})


def images_from_html(data: bytes | str, url: str = "") -> list[ImageResult]:
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    parser = _ImageParser()
    try:
        parser.feed(text)
    except Exception:
        pass
    page = parse_page(data, url)
    base = parser._base or url
    out: list[ImageResult] = []
    seen: set[str] = set()
    for row in parser.images:
        raw = (row.get("src") or "").strip()
        if not raw or raw.startswith(("data:", "javascript:", "blob:")):
            continue
        absolute = urllib.parse.urljoin(base, raw)
        if not absolute.startswith(("http://", "https://")) or absolute in seen:
            continue
        seen.add(absolute)
        out.append(ImageResult(
            title=row.get("alt") or page.title or urllib.parse.urlparse(absolute).path,
            image_url=absolute, page_url=url, snippet=row.get("alt") or "",
            source="page"))
        if len(out) >= 40:
            break
    return out


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _clean_web_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\ue000", "").replace("\ue001", "")).strip()


def parse_bing_images(data: bytes | str, max_results: int = 8) -> list[ImageResult]:
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    out: list[ImageResult] = []
    seen: set[str] = set()
    for raw in re.findall(r'm="([^"]+)"', text):
        try:
            item = json.loads(html.unescape(raw))
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(item, dict):
            continue
        image = str(item.get("murl") or "").strip()
        if not image.startswith(("http://", "https://")) or image in seen:
            continue
        seen.add(image)
        out.append(ImageResult(
            title=_clean_web_text(str(item.get("t") or item.get("desc") or "")),
            image_url=image,
            page_url=str(item.get("purl") or ""),
            thumbnail=str(item.get("turl") or ""),
            snippet=_clean_web_text(str(item.get("desc") or "")),
            source="bing"))
        if len(out) >= max_results:
            break
    return out


def parse_commons_images(payload: dict[str, Any], max_results: int = 8) -> list[ImageResult]:
    pages = (payload.get("query") or {}).get("pages") or {}
    rows = sorted(pages.values(), key=lambda p: p.get("index", 0))
    out: list[ImageResult] = []
    for page in rows:
        info = (page.get("imageinfo") or [{}])[0]
        image = info.get("thumburl") or info.get("url") or ""
        if not image:
            continue
        meta = info.get("extmetadata") or {}
        def val(key):
            return _strip_html(str((meta.get(key) or {}).get("value") or ""))
        title = str(page.get("title") or "Image").removeprefix("File:")
        out.append(ImageResult(
            title=title, image_url=image,
            page_url=info.get("descriptionurl") or "",
            thumbnail=info.get("thumburl") or image,
            snippet=val("ImageDescription") or title,
            source="wikimedia",
            creator=val("Artist") or val("Credit"),
            license=val("LicenseShortName") or val("License"),
            width=int(info.get("thumbwidth") or info.get("width") or 0),
            height=int(info.get("thumbheight") or info.get("height") or 0)))
        if len(out) >= max_results:
            break
    return out


def search_commons_images(query: str, max_results: int = 8) -> list[ImageResult]:
    params = urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": query,
        "gsrnamespace": "6", "gsrlimit": str(max_results),
        "prop": "imageinfo", "iiprop": "url|extmetadata",
        "iiurlwidth": "1600", "format": "json",
    })
    data, _ctype, _final = fetch_bytes(
        "https://commons.wikimedia.org/w/api.php?" + params,
        max_bytes=2_000_000)
    try:
        payload = json.loads(data.decode("utf-8", "replace"))
    except json.JSONDecodeError as exc:
        raise ResearchError("Wikimedia Commons did not return JSON") from exc
    return parse_commons_images(payload, max_results)


def search_images(query: str, max_results: int = 8,
                  source: str = "web") -> list[ImageResult]:
    query = (query or "").strip()
    if not query:
        raise ResearchError("empty image query")
    max_results = max(1, min(int(max_results or 8), 16))
    if source == "licensed":
        return search_commons_images(query, max_results)
    import os

    searx = os.environ.get("REVERSEAI_SEARCH_URL")
    if searx:
        sep = "&" if "?" in searx else "?"
        url = (f"{searx}{sep}q={urllib.parse.quote(query)}"
               "&categories=images&format=json")
        try:
            data, _ctype, _final = fetch_bytes(url, max_bytes=1_500_000)
            payload = json.loads(data.decode("utf-8", "replace"))
            rows = []
            for r in (payload.get("results") or [])[:max_results]:
                image = str(r.get("img_src") or r.get("thumbnail_src") or "")
                if not image.startswith(("http://", "https://")):
                    continue
                rows.append(ImageResult(
                    title=_clean_web_text(str(r.get("title") or "")),
                    image_url=image,
                    page_url=str(r.get("url") or ""),
                    thumbnail=str(r.get("thumbnail_src") or ""),
                    snippet=_clean_web_text(str(r.get("content") or "")),
                    source="searx"))
            if rows:
                return rows
        except (ResearchError, json.JSONDecodeError):
            pass
    url = "https://www.bing.com/images/search?" + urllib.parse.urlencode(
        {"q": query, "form": "HDRSC2"})
    data, _ctype, _final = fetch_bytes(url, max_bytes=3_000_000)
    rows = parse_bing_images(data, max_results)
    if not rows:
        raise ResearchError("no image results")
    return rows


def images_from_page(url: str) -> list[ImageResult]:
    data, _ctype, final = fetch_bytes(url, max_bytes=4_000_000)
    rows = images_from_html(data, final)
    if not rows:
        raise ResearchError("no images found on that page")
    return rows[:40]


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
