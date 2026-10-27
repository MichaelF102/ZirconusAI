"""End-to-end smoke test: real uvicorn server, real HTTP + SSE, fake external providers.

Exercises the whole stack (FastAPI, background execution, LangGraph, SQLite, SSE) the way the
Next.js frontend does, without consuming any API quota.
"""

import json
import socket
import threading
import time

import httpx
import uvicorn

from app.main import create_app
from tests.fakes import FakeExtractor, FakeSearch, default_llm


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_full_stack_smoke(settings):
    app = create_app(settings, dependency_factory=lambda _s: (default_llm(), FakeSearch(), FakeExtractor()))
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{base}/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)

        origin = settings.frontend_origin
        created = httpx.post(f"{base}/api/research", json={"question": "How is agentic AI changing data engineering?"},
                             headers={"Origin": origin})
        assert created.status_code == 202
        assert created.headers["access-control-allow-origin"] == origin
        research_id = created.json()["id"]

        types = []
        with httpx.stream("GET", f"{base}/api/research/{research_id}/events", timeout=30) as resp:
            event = None
            for line in resp.iter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and event == "progress":
                    types.append(json.loads(line[5:])["type"])
                elif line.startswith("data:") and event == "end":
                    break
        assert types[0] == "queued" and types[-1] == "completed"
        assert "critic" in types and "quality" in types

        report = httpx.get(f"{base}/api/research/{research_id}/report").json()
        assert report["status"] == "completed"
        assert "## References" in report["report_markdown"]
    finally:
        server.should_exit = True
        thread.join(timeout=10)
