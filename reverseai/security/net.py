"""Network safety helpers — public-only fetching with redirect validation.

Any feature that fetches a URL on behalf of a user (clone, browse, research)
must defend against SSRF. This module validates the scheme and host on *every*
redirect hop, resolves DNS to reject private/link-local/loopback addresses, and
caps the response size. It is deliberately dependency-free.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 15.0
DEFAULT_MAX_BYTES = 6 * 1024 * 1024
MAX_REDIRECTS = 5


class NetworkError(Exception):
    pass


def is_public_host(host: str) -> bool:
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
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return False
    return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def validate_url(url: str, allow_private: bool = False) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise NetworkError(f"only http/https is supported, not {parsed.scheme!r}")
    if not parsed.hostname:
        raise NetworkError("URL has no host")
    if not allow_private and not is_public_host(parsed.hostname):
        raise NetworkError(f"refusing to fetch a non-public host: {parsed.hostname}")
    return url


def fetch(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    allow_private: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    user_agent: str = "Mozilla/5.0 (compatible; ReverseAI/1.0)",
    accept: str = "*/*",
) -> tuple[bytes, str, str]:
    """Fetch a URL safely. Returns ``(body, content_type, final_url)``.

    Redirects are followed manually so each hop is validated. The body is capped
    at ``max_bytes`` (we read one extra byte to detect overflow).
    """
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        validate_url(current, allow_private)
        req = urllib.request.Request(current, headers={
            "User-Agent": user_agent,
            "Accept": accept,
        })
        try:
            resp = _OPENER.open(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                loc = exc.headers.get("Location")
                if not loc:
                    raise NetworkError(f"redirect without Location from {current}")
                current = urllib.parse.urljoin(current, loc)
                continue
            raise NetworkError(f"HTTP {exc.code} from {current}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise NetworkError(f"fetch failed: {exc}") from exc
        with resp:
            data = resp.read(max_bytes + 1)
            ctype = resp.headers.get("Content-Type", "")
            final = resp.geturl()
        if len(data) > max_bytes:
            raise NetworkError(f"response exceeds {max_bytes} bytes")
        return data, ctype, final
    raise NetworkError("too many redirects")
