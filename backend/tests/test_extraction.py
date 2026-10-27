import httpx
import pytest

from app.tools.extraction import ExtractionError, UnsafeURLError, WebPageExtractor, assert_public_url, clean_text

ARTICLE = "<html><head><title>Agents</title></head><body><nav>menu</nav><article><h1>Agents</h1>" + "".join(
    f"<p>Paragraph {i}: data engineering teams are experimenting with AI agents for pipeline maintenance, "
    f"data quality checks and schema migrations in production environments.</p>"
    for i in range(8)
) + "</article><footer>footer</footer></body></html>"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://127.0.0.1:80/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "http://user:pass@example.com/",
        "http://example.com:22/",
        "http://service.internal/",
    ],
)
async def test_unsafe_urls_are_rejected(url):
    with pytest.raises(UnsafeURLError):
        await assert_public_url(url, resolve=False)


async def test_hostnames_resolving_to_private_ips_are_rejected(monkeypatch):
    async def fake_getaddrinfo(host, port, **_kw):
        return [(None, None, None, "", ("10.1.2.3", port))]

    import asyncio

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURLError, match="non-public"):
        await assert_public_url("https://evil.example.com/")


def _extractor(handler) -> WebPageExtractor:
    return WebPageExtractor(transport=httpx.MockTransport(handler), resolve_dns=False, max_chars=5000)


async def test_extracts_main_content_from_html():
    result = await _extractor(lambda req: httpx.Response(200, html=ARTICLE)).extract("https://example.com/a")
    assert "pipeline maintenance" in result.text
    assert "menu" not in result.text


async def test_redirect_to_private_address_is_blocked():
    def handler(request: httpx.Request):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})

    with pytest.raises(UnsafeURLError):
        await _extractor(handler).extract("https://example.com/redirect")


async def test_safe_redirect_is_followed():
    def handler(request: httpx.Request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, html=ARTICLE)

    result = await _extractor(handler).extract("https://example.com/old")
    assert result.final_url == "https://example.com/new"


@pytest.mark.parametrize(
    "response, message",
    [
        (httpx.Response(404), "HTTP 404"),
        (httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"}), "Unsupported content"),
        (httpx.Response(200, html="<html><body><p>tiny</p></body></html>"), "No readable"),
    ],
)
async def test_extraction_failures_raise_extraction_error(response, message):
    with pytest.raises(ExtractionError, match=message):
        await _extractor(lambda req: response).extract("https://example.com/x")


async def test_oversized_pages_are_rejected():
    extractor = WebPageExtractor(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, html="x" * 50_000)),
        resolve_dns=False, max_bytes=10_000,
    )
    with pytest.raises(ExtractionError, match="too large"):
        await extractor.extract("https://example.com/big")


async def test_timeouts_become_extraction_errors():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ExtractionError, match="Timed out"):
        await _extractor(handler).extract("https://example.com/slow")


def test_clean_text_truncates_and_normalizes():
    assert clean_text("a  b\n\n\n\nc", 100) == "a b\n\nc"
    assert clean_text("word " * 100, 50).endswith("[truncated]")
