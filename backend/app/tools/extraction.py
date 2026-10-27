"""Safe, read-only fetching and readable-text extraction for web pages."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura

logger = logging.getLogger(__name__)

_ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
_MAX_REDIRECTS = 5
_USER_AGENT = "Mozilla/5.0 (compatible; ZirconusAI/0.1; +read-only research fetcher)"


class UnsafeURLError(ValueError):
    """Raised when a URL targets a destination we refuse to fetch."""


class ExtractionError(Exception):
    pass


@dataclass
class ExtractionResult:
    text: str
    final_url: str
    title: str | None = None
    published_at: str | None = None


class PageExtractor(Protocol):
    async def extract(self, url: str) -> ExtractionResult: ...


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local)


def _check_url_shape(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError(f"Scheme not allowed: {parts.scheme or '(none)'}")
    if parts.username or parts.password:
        raise UnsafeURLError("Credentials in URL are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURLError("URL has no host")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
        raise UnsafeURLError("Local hostnames are not allowed")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeURLError("Invalid port") from exc
    if port not in (80, 443, 8080, 8443):
        raise UnsafeURLError(f"Port {port} is not allowed")
    return host, port


async def assert_public_url(url: str, resolve: bool = True) -> None:
    """Reject URLs that resolve to loopback, private, link-local or otherwise non-public addresses."""
    host, port = _check_url_shape(url)
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not _ip_is_public(literal):
            raise UnsafeURLError("Non-public IP address")
        return
    if not resolve:
        return
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ExtractionError(f"DNS resolution failed for {host}") from exc
    if not infos:
        raise ExtractionError(f"DNS resolution returned no addresses for {host}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not _ip_is_public(ip):
            raise UnsafeURLError(f"{host} resolves to a non-public address")


def clean_text(text: str, max_chars: int) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > max_chars:
        cut = text[:max_chars]
        boundary = cut.rfind("\n")
        text = (cut[:boundary] if boundary > max_chars * 0.8 else cut).rstrip() + "\n[truncated]"
    return text


class WebPageExtractor:
    """Fetches public pages with SSRF protection and extracts the main text with Trafilatura."""

    def __init__(self, timeout: float = 20, max_bytes: int = 3_000_000, max_chars: int = 12000,
                 transport: httpx.AsyncBaseTransport | None = None, resolve_dns: bool = True):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_chars = max_chars
        self._transport = transport
        self._resolve_dns = resolve_dns

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> tuple[str, str, str]:
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            await assert_public_url(current, resolve=self._resolve_dns)
            async with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise ExtractionError("Redirect without location")
                    current = urljoin(current, location)
                    continue
                if resp.status_code >= 400:
                    raise ExtractionError(f"HTTP {resp.status_code}")
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and not ctype.startswith(_ALLOWED_CONTENT_TYPES):
                    raise ExtractionError(f"Unsupported content type: {ctype}")
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > self.max_bytes:
                    raise ExtractionError("Page too large")
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ExtractionError("Page too large")
                    chunks.append(chunk)
                encoding = resp.charset_encoding or "utf-8"
                body = b"".join(chunks).decode(encoding, errors="replace")
                return body, str(resp.url), ctype
        raise ExtractionError("Too many redirects")

    async def extract(self, url: str) -> ExtractionResult:
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,  # redirects are followed manually so each hop is re-validated
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8"},
            transport=self._transport,
        ) as client:
            try:
                body, final_url, ctype = await self._fetch(client, url)
            except httpx.TimeoutException as exc:
                raise ExtractionError("Timed out") from exc
            except httpx.HTTPError as exc:
                raise ExtractionError(f"Request failed: {type(exc).__name__}") from exc

        if ctype == "text/plain":
            return ExtractionResult(text=clean_text(body, self.max_chars), final_url=final_url)

        # Trafilatura is CPU-bound; keep it off the event loop.
        def _parse() -> tuple[str | None, str | None, str | None]:
            text = trafilatura.extract(body, url=final_url, include_comments=False, include_tables=True,
                                       favor_precision=True)
            meta = trafilatura.extract_metadata(body, default_url=final_url)
            return text, (meta.title if meta else None), (meta.date if meta else None)

        text, title, published = await asyncio.to_thread(_parse)
        if not text or len(text.strip()) < 200:
            raise ExtractionError("No readable main content found")
        return ExtractionResult(text=clean_text(text, self.max_chars), final_url=final_url, title=title,
                                published_at=published)
