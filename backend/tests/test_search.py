import httpx
import pytest
import respx

from app.graph.nodes import merge_search_results
from app.graph.state import PendingQuery
from app.tools.search import (
    SearchError,
    SearchHit,
    SearchOptions,
    TavilySearch,
    classify_source,
    dedupe_hits,
    normalize_url,
)


def test_normalize_url_removes_tracking_and_trivial_differences():
    a = normalize_url("http://www.Example.com/path/?utm_source=x&b=2&a=1#section")
    b = normalize_url("https://example.com/path?a=1&b=2")
    assert a == b == "https://example.com/path?a=1&b=2"


def test_dedupe_hits_drops_duplicates_and_non_http():
    hits = [
        SearchHit("A", "https://example.com/a", ""),
        SearchHit("A again", "https://www.example.com/a/?utm_medium=email", ""),
        SearchHit("FTP", "ftp://example.com/file", ""),
        SearchHit("B", "https://example.com/b", ""),
    ]
    assert [h.title for h in dedupe_hits(hits)] == ["A", "B"]


def test_merge_assigns_stable_ids_dedupes_across_subquestions_and_caps():
    hits = [SearchHit(f"T{i}", f"https://site{i}.com/page", f"snippet {i}") for i in range(5)]
    q1 = PendingQuery(query="q1", subquestion_id="Q1")
    q2 = PendingQuery(query="q2", subquestion_id="Q2")
    sources = merge_search_results([], [(q1, hits[:4]), (q2, [hits[0], hits[4]])], max_per_subquestion=3)
    assert [s.source_id for s in sources] == ["S1", "S2", "S3", "S4"]
    assert sources[0].subquestion_ids == ["Q1", "Q2"]  # shared URL is not duplicated
    assert sources[3].url == "https://site4.com/page"
    # A later round continues numbering from the existing sources.
    more = merge_search_results(sources, [(q1, [SearchHit("New", "https://new.com", "")])], 3)
    assert more[-1].source_id == "S5" and len(more) == 5


def test_classify_source():
    assert classify_source("https://www.cdc.gov/x") == "official"
    assert classify_source("https://arxiv.org/abs/1234") == "academic"
    assert classify_source("https://docs.python.org/3/") == "documentation"
    assert classify_source("https://www.reuters.com/tech") == "news"
    assert classify_source("https://someone.substack.com/p/x") == "blog"


@respx.mock
async def test_tavily_normalizes_results_and_sends_filters():
    route = respx.post(TavilySearch.endpoint).mock(
        return_value=httpx.Response(200, json={"results": [
            {"title": "Doc", "url": "https://docs.example.com", "content": "snippet", "score": 0.8,
             "published_date": "2025-01-02"},
            {"title": "No URL", "content": "dropped"},
        ]})
    )
    client = TavilySearch("tvly-test-key", max_retries=0)
    hits = await client.search("query", SearchOptions(max_results=3, include_domains=["example.com"]))
    assert [(h.title, h.url, h.published_at) for h in hits] == [("Doc", "https://docs.example.com", "2025-01-02")]
    sent = route.calls[0].request
    assert sent.headers["Authorization"] == "Bearer tvly-test-key"
    assert b'"include_domains":["example.com"]' in sent.content


@respx.mock
async def test_tavily_maps_auth_and_server_errors():
    respx.post(TavilySearch.endpoint).mock(return_value=httpx.Response(401))
    with pytest.raises(SearchError, match="credentials"):
        await TavilySearch("k" * 10, max_retries=0).search("q", SearchOptions())

    respx.post(TavilySearch.endpoint).mock(return_value=httpx.Response(500))
    with pytest.raises(SearchError, match="HTTP 500"):
        await TavilySearch("k" * 10, max_retries=0).search("q", SearchOptions())


@respx.mock
async def test_tavily_retries_transient_errors(monkeypatch):
    monkeypatch.setattr("app.tools.retry.asyncio.sleep", lambda *_: _noop())
    route = respx.post(TavilySearch.endpoint).mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"results": []})]
    )
    assert await TavilySearch("k" * 10, max_retries=2).search("q", SearchOptions()) == []
    assert route.call_count == 2


async def _noop():
    return None
