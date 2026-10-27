from __future__ import annotations

import pytest

from app.config import Settings
from app.graph.context import RunContext
from tests.fakes import FakeExtractor, FakeSearch, default_llm


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key="",
        tavily_api_key="",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        max_subquestions=2,
        max_sources_per_subquestion=3,
        max_revision_cycles=2,
        llm_max_retries=0,
        max_research_seconds=30,
    )


@pytest.fixture
def make_ctx(settings):
    def _make(llm=None, search=None, extractor=None, events=None, **kwargs) -> RunContext:
        sink = events if events is not None else []
        return RunContext(
            settings=kwargs.pop("settings", settings),
            llm=llm or default_llm(),
            search=search or FakeSearch(),
            extractor=extractor or FakeExtractor(),
            emit=lambda t, n, m, d: sink.append((t, n, m, d)),
            **kwargs,
        )

    return _make
