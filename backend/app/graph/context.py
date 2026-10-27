"""Per-run dependencies injected into graph nodes via ``config["configurable"]["ctx"]``."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from app.config import Settings
from app.schemas.evidence import SourceRecord
from app.schemas.research import ResearchPlan, ResearchReport, UsageStats
from app.tools.extraction import PageExtractor
from app.tools.llm import LLMClient, LLMError
from app.tools.retry import is_transient, with_retries
from app.tools.search import SearchProvider

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

EmitFn = Callable[[str, str | None, str, dict[str, Any] | None], None]


def _noop(*_args: Any, **_kwargs: Any) -> None:
    return None


@dataclass
class DepthProfile:
    subquestions: int
    queries_per_subquestion: int
    sources_per_subquestion: int


@dataclass
class RunContext:
    settings: Settings
    llm: LLMClient
    search: SearchProvider
    extractor: PageExtractor
    emit: EmitFn = _noop
    on_plan: Callable[[ResearchPlan], None] = _noop
    on_sources: Callable[[list[SourceRecord]], None] = _noop
    on_stage: Callable[[str], None] = _noop
    on_usage: Callable[[UsageStats], None] = _noop
    on_revision: Callable[[int], None] = _noop
    on_report: Callable[[ResearchReport], None] = _noop
    usage: UsageStats = field(default_factory=UsageStats)
    search_semaphore: asyncio.Semaphore | None = None
    fetch_semaphore: asyncio.Semaphore | None = None

    def __post_init__(self) -> None:
        if self.search_semaphore is None:
            self.search_semaphore = asyncio.Semaphore(self.settings.max_concurrent_searches)
        if self.fetch_semaphore is None:
            self.fetch_semaphore = asyncio.Semaphore(self.settings.max_concurrent_fetches)

    def depth_profile(self, depth: str, override_sources: int | None = None) -> DepthProfile:
        s = self.settings
        if depth == "quick":
            profile = DepthProfile(min(3, s.max_subquestions), 1, min(3, s.max_sources_per_subquestion))
        elif depth == "deep":
            profile = DepthProfile(min(s.max_subquestions + 1, 8), 2, s.max_sources_per_subquestion)
        else:
            profile = DepthProfile(s.max_subquestions, 2, s.max_sources_per_subquestion)
        if override_sources:
            profile.sources_per_subquestion = override_sources
        return profile

    async def structured(self, schema: type[T], system: str, prompt: str, *, label: str) -> T:
        """Call the LLM with timeout, bounded retries and usage accounting."""

        async def _call() -> T:
            self.usage.llm_calls += 1
            result, usage = await asyncio.wait_for(
                self.llm.generate(schema, system, prompt), timeout=self.settings.llm_timeout_seconds
            )
            self.usage.input_tokens += usage.get("input_tokens", 0)
            self.usage.output_tokens += usage.get("output_tokens", 0)
            return result

        try:
            return await with_retries(
                _call,
                max_retries=self.settings.llm_max_retries,
                base_delay=2.0,
                label=f"LLM {label}",
                retry_if=lambda exc: isinstance(exc, LLMError) or is_transient(exc),
            )
        finally:
            self.on_usage(self.usage)


def get_ctx(config: RunnableConfig) -> RunContext:
    return config["configurable"]["ctx"]
