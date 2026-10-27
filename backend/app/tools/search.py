"""Web search providers and result normalisation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from app.tools.retry import with_retries

logger = logging.getLogger(__name__)

_TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid", "spm"}


class SearchError(Exception):
    """Raised when a search provider fails permanently."""


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    score: float | None = None
    published_at: str | None = None
    raw_content: str | None = None


@dataclass
class SearchOptions:
    max_results: int = 5
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, options: SearchOptions) -> list[SearchHit]: ...


def normalize_url(url: str) -> str:
    """Canonical form used for de-duplication (not for fetching)."""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = parts.port
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (k, v)
            for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
        )
    )
    return urlunsplit(("https" if scheme in ("http", "https") else scheme, netloc, path, query, ""))


def domain_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def dedupe_hits(hits: list[SearchHit], seen: set[str] | None = None) -> list[SearchHit]:
    """Drop hits whose normalised URL was already seen. Mutates ``seen`` when provided."""
    seen = seen if seen is not None else set()
    unique: list[SearchHit] = []
    for hit in hits:
        if not hit.url.lower().startswith(("http://", "https://")):
            continue
        key = normalize_url(hit.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def classify_source(url: str) -> str:
    domain = domain_of(url)
    path = urlsplit(url).path.lower()
    if domain.endswith((".gov", ".mil", ".int")) or ".gov." in domain or domain.endswith(".europa.eu"):
        return "official"
    if (
        domain.endswith(".edu")
        or ".ac." in domain
        or domain in {"arxiv.org", "nature.com", "science.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
                      "sciencedirect.com", "springer.com", "link.springer.com", "acm.org", "dl.acm.org",
                      "ieeexplore.ieee.org", "plos.org", "journals.plos.org", "semanticscholar.org", "biorxiv.org",
                      "medrxiv.org", "thelancet.com", "nejm.org", "bmj.com", "jamanetwork.com", "cell.com"}
    ):
        return "academic"
    if domain.startswith(("docs.", "developer.", "developers.")) or "/docs" in path or "/documentation" in path:
        return "documentation"
    if domain in {"wikipedia.org", "en.wikipedia.org", "britannica.com"}:
        return "reference"
    if domain in {"reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nytimes.com", "theguardian.com",
                  "ft.com", "wsj.com", "bloomberg.com", "economist.com", "washingtonpost.com", "cnbc.com",
                  "techcrunch.com", "theverge.com", "wired.com", "arstechnica.com", "npr.org"}:
        return "news"
    if domain.startswith("blog.") or "/blog" in path or domain.endswith(("medium.com", "substack.com")):
        return "blog"
    return "other"


class TavilySearch:
    """Tavily search API client (https://docs.tavily.com)."""

    name = "tavily"
    endpoint = "https://api.tavily.com/search"

    def __init__(self, api_key: str, timeout: float = 20, max_retries: int = 3,
                 client: httpx.AsyncClient | None = None):
        if not api_key:
            raise SearchError("TAVILY_API_KEY is not configured")
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._client = client

    async def search(self, query: str, options: SearchOptions) -> list[SearchHit]:
        payload: dict = {
            "query": query[:400],
            "max_results": options.max_results,
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
        }
        if options.include_domains:
            payload["include_domains"] = options.include_domains
        if options.exclude_domains:
            payload["exclude_domains"] = options.exclude_domains
        if options.start_date:
            payload["start_date"] = options.start_date.isoformat()
        if options.end_date:
            payload["end_date"] = options.end_date.isoformat()

        async def _call() -> dict:
            client = self._client or httpx.AsyncClient(timeout=self._timeout)
            try:
                resp = await client.post(
                    self.endpoint,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=self._timeout,
                )
            finally:
                if self._client is None:
                    await client.aclose()
            if resp.status_code in (401, 403):
                raise SearchError("Search API rejected the credentials (check TAVILY_API_KEY)")
            if resp.status_code == 432 or resp.status_code == 433:
                raise SearchError("Search API usage limit reached for this plan")
            resp.raise_for_status()
            return resp.json()

        try:
            data = await with_retries(_call, max_retries=self._max_retries, label="tavily search")
        except SearchError:
            raise
        except httpx.HTTPStatusError as exc:
            raise SearchError(f"Search API returned HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise SearchError(f"Search request failed: {type(exc).__name__}") from exc

        hits = []
        for item in data.get("results", []) or []:
            url = item.get("url")
            if not url:
                continue
            hits.append(
                SearchHit(
                    title=(item.get("title") or url).strip(),
                    url=url,
                    snippet=(item.get("content") or "").strip(),
                    score=item.get("score"),
                    published_at=item.get("published_date"),
                    raw_content=item.get("raw_content"),
                )
            )
        return hits
