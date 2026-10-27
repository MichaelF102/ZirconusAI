import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fakes import FakeExtractor, FakeSearch, default_llm

QUESTION = "How is agentic AI changing data engineering?"


def _factory(llm=None, search=None):
    return lambda _settings: (llm or default_llm(), search or FakeSearch(), FakeExtractor())


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, dependency_factory=_factory())) as c:
        yield c


def _wait(client, research_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        detail = client.get(f"/api/research/{research_id}").json()
        if detail["status"] not in ("queued", "running"):
            return detail
        time.sleep(0.05)
    raise AssertionError("research did not finish")


def _sse(client, research_id, headers=None):
    events = []
    with client.stream("GET", f"/api/research/{research_id}/events", headers=headers or {}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        current = {}
        for line in resp.iter_lines():
            if not line:
                if current:
                    events.append(current)
                    if current.get("event") == "end":
                        break
                current = {}
                continue
            if line.startswith(":"):
                continue
            key, _, value = line.partition(":")
            current[key] = value.lstrip()
    return events


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_submit_and_retrieve_completed_research(client):
    resp = client.post("/api/research", json={"question": QUESTION, "depth": "quick"})
    assert resp.status_code == 202
    research_id = resp.json()["id"]

    detail = _wait(client, research_id)
    assert detail["status"] == "completed"
    assert detail["has_report"] is True
    assert detail["plan"]["subquestions"][0]["id"] == "Q1"
    assert detail["usage"]["llm_calls"] == 4
    assert detail["usage"]["search_calls"] >= 1
    assert detail["elapsed_seconds"] is not None

    report = client.get(f"/api/research/{research_id}/report").json()
    assert report["research_id"] == research_id
    assert report["quality_assessment"]["status"] == "passed"
    source_ids = {s["source_id"] for s in report["sources"]}
    assert "[S1]" in report["report_markdown"] and "S1" in source_ids

    sources = client.get(f"/api/research/{research_id}/sources").json()
    assert [s["source_id"] for s in sources] == ["S1", "S2", "S3"]
    assert {s["extraction_status"] for s in sources} == {"extracted"}

    listing = client.get("/api/research").json()
    assert listing[0]["id"] == research_id and listing[0]["title"]


def test_sse_stream_is_well_formed_and_resumable(client):
    research_id = client.post("/api/research", json={"question": QUESTION}).json()["id"]
    events = _sse(client, research_id)
    progress = [e for e in events if e["event"] == "progress"]
    payloads = [json.loads(e["data"]) for e in progress]
    assert payloads[0]["type"] == "queued"
    assert payloads[-1]["type"] == "completed"
    assert events[-1]["event"] == "end" and json.loads(events[-1]["data"])["status"] == "completed"
    assert all(p["research_id"] == research_id and p["timestamp"] for p in payloads)
    ids = [int(e["id"]) for e in progress]
    assert ids == sorted(ids)
    stage_nodes = [p["node"] for p in payloads if p["type"] == "stage_started"]
    assert stage_nodes[0] == "planner" and stage_nodes[-1] == "finalizer"
    # Nothing secret or prompt-like leaks into events.
    blob = json.dumps(payloads)
    assert "You are" not in blob and "api_key" not in blob.lower()

    # Reconnect with Last-Event-ID: only later events are replayed.
    resumed = _sse(client, research_id, headers={"Last-Event-ID": str(ids[2])})
    resumed_ids = [int(e["id"]) for e in resumed if e["event"] == "progress"]
    assert resumed_ids == ids[3:]


def test_failed_research_reports_error(settings):
    app = create_app(settings, dependency_factory=_factory(search=FakeSearch(empty=True)))
    with TestClient(app) as client:
        research_id = client.post("/api/research", json={"question": QUESTION}).json()["id"]
        detail = _wait(client, research_id)
        assert detail["status"] == "failed"
        assert "No sources were found" in detail["error"]
        assert client.get(f"/api/research/{research_id}/report").status_code == 404
        events = _sse(client, research_id)
        assert json.loads(events[-2]["data"])["type"] == "failed"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"question": "short"},
        {"question": "x" * 501},
        {"question": "1234567890 !!!"},
        {"question": QUESTION, "depth": "extreme"},
        {"question": QUESTION, "include_domains": ["not a domain"]},
        {"question": QUESTION, "start_date": "2025-05-01", "end_date": "2024-01-01"},
        {"question": QUESTION, "max_sources_per_subquestion": 50},
    ],
)
def test_malformed_requests_are_rejected(client, body):
    resp = client.post("/api/research", json=body)
    assert resp.status_code == 422
    assert resp.json()["detail"]


def test_domain_filters_are_normalized_and_forwarded(settings):
    search = FakeSearch()
    with TestClient(create_app(settings, dependency_factory=_factory(search=search))) as client:
        body = {"question": QUESTION, "include_domains": ["https://www.Example.com/path", "example.com"]}
        research_id = client.post("/api/research", json=body).json()["id"]
        _wait(client, research_id)
        assert client.get(f"/api/research/{research_id}").json()["request"]["include_domains"] == ["example.com"]
        assert search.calls[0][1].include_domains == ["example.com"]


def test_unknown_research_returns_404(client):
    for path in ["", "/report", "/sources", "/events"]:
        assert client.get(f"/api/research/does-not-exist{path}").status_code == 404


def test_missing_credentials_return_503(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json()["missing_configuration"] == ["GEMINI_API_KEY", "TAVILY_API_KEY"]
        resp = client.post("/api/research", json={"question": QUESTION})
        assert resp.status_code == 503
        assert "GEMINI_API_KEY" in resp.json()["detail"]


def test_create_is_rate_limited(settings):
    limited = settings.model_copy(update={"create_rate_limit_per_minute": 2})
    with TestClient(create_app(limited, dependency_factory=_factory())) as client:
        codes = [client.post("/api/research", json={"question": QUESTION}).status_code for _ in range(3)]
        assert codes == [202, 202, 429]


def test_cancel_running_research(settings):
    import asyncio

    class SlowLLM:
        name = "slow"

        async def generate(self, schema, system, prompt):
            await asyncio.sleep(30)

    with TestClient(create_app(settings, dependency_factory=_factory(llm=SlowLLM()))) as client:
        research_id = client.post("/api/research", json={"question": QUESTION}).json()["id"]
        time.sleep(0.2)
        resp = client.post(f"/api/research/{research_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"
        assert client.post(f"/api/research/{research_id}/cancel").status_code == 409


def test_history_persists_across_restarts(settings):
    with TestClient(create_app(settings, dependency_factory=_factory())) as client:
        research_id = client.post("/api/research", json={"question": QUESTION}).json()["id"]
        _wait(client, research_id)
    with TestClient(create_app(settings, dependency_factory=_factory())) as client:
        assert client.get("/api/research").json()[0]["id"] == research_id
        assert client.get(f"/api/research/{research_id}/report").status_code == 200


def test_interrupted_tasks_are_marked_failed_on_startup(settings):
    from app.db.repository import ResearchRepository
    from app.db.session import Database
    from app.schemas.research import ResearchRequest

    db = Database(settings.database_url)
    db.create_all()
    ResearchRepository(db).create_task("orphan", ResearchRequest(question=QUESTION))
    with TestClient(create_app(settings, dependency_factory=_factory())) as client:
        detail = client.get("/api/research/orphan").json()
        assert detail["status"] == "failed" and "restarted" in detail["error"]
