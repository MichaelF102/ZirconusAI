"""Runs research workflows in the background and persists their progress."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any

from app.config import Settings
from app.db.models import utcnow
from app.db.repository import ResearchRepository
from app.graph.context import RunContext
from app.graph.nodes import WorkflowError
from app.graph.workflow import build_workflow
from app.schemas.research import ResearchRequest, ResearchStatus
from app.tools.extraction import PageExtractor, WebPageExtractor
from app.tools.llm import GeminiLLM, LLMClient, LLMError
from app.tools.search import SearchError, SearchProvider, TavilySearch

logger = logging.getLogger(__name__)

Dependencies = tuple[LLMClient, SearchProvider, PageExtractor]
DependencyFactory = Callable[[Settings], Dependencies]


def default_dependencies(settings: Settings) -> Dependencies:
    missing = settings.missing_credentials()
    if missing:
        raise WorkflowError(f"Missing configuration: {', '.join(missing)}. Add them to the backend .env file.")
    llm = GeminiLLM(settings.gemini_api_key, settings.gemini_model, timeout=settings.llm_timeout_seconds)
    search = TavilySearch(settings.tavily_api_key, timeout=settings.request_timeout_seconds,
                          max_retries=settings.llm_max_retries)
    extractor = WebPageExtractor(
        timeout=settings.request_timeout_seconds,
        max_bytes=settings.max_fetch_bytes,
        max_chars=settings.max_source_chars,
    )
    return llm, search, extractor


class ResearchService:
    def __init__(
        self,
        repo: ResearchRepository,
        settings: Settings,
        dependency_factory: DependencyFactory = default_dependencies,
        requires_credentials: bool = True,
    ):
        self.repo = repo
        self.settings = settings
        self._factory = dependency_factory
        self._requires_credentials = requires_credentials
        self._tasks: dict[str, asyncio.Task] = {}
        self._run_slots: asyncio.Semaphore | None = None
        self._graph = build_workflow()

    def missing_configuration(self) -> list[str]:
        return self.settings.missing_credentials() if self._requires_credentials else []

    # ---- lifecycle ---------------------------------------------------------
    def start(self, request: ResearchRequest) -> str:
        research_id = str(uuid.uuid4())
        self.repo.create_task(research_id, request)
        self.repo.add_event(research_id, "queued", "Research task queued", data={"depth": request.depth})
        task = asyncio.create_task(self._run(research_id, request), name=f"research-{research_id}")
        self._tasks[research_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(research_id, None))
        return research_id

    def is_active(self, research_id: str) -> bool:
        return research_id in self._tasks

    async def cancel(self, research_id: str) -> bool:
        task = self._tasks.get(research_id)
        if task is None or task.done():
            return False
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        return True

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def wait(self, research_id: str) -> None:
        """Await a running task (used by tests and the evaluation runner)."""
        task = self._tasks.get(research_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    # ---- execution ---------------------------------------------------------
    def _context(self, research_id: str, deps: Dependencies) -> RunContext:
        llm, search, extractor = deps
        repo = self.repo

        def emit(type_: str, node: str | None, message: str, data: dict[str, Any] | None) -> None:
            logger.info("[%s] %s %s", research_id[:8], node or "-", message)
            repo.add_event(research_id, type_, message, node=node, data=data)

        return RunContext(
            settings=self.settings,
            llm=llm,
            search=search,
            extractor=extractor,
            emit=emit,
            on_plan=lambda plan: repo.update_task(research_id, plan=plan.model_dump(mode="json")),
            on_sources=lambda sources: repo.replace_sources(research_id, sources),
            on_stage=lambda node: repo.update_task(research_id, current_stage=node),
            on_usage=lambda usage: repo.update_task(research_id, usage=usage.model_dump()),
            on_revision=lambda n: repo.update_task(research_id, revision_count=n),
            on_report=repo.save_report,
        )

    async def _run(self, research_id: str, request: ResearchRequest) -> None:
        if self._run_slots is None:
            self._run_slots = asyncio.Semaphore(self.settings.max_concurrent_research)
        config: dict[str, Any] = {"configurable": {"thread_id": research_id}, "recursion_limit": 50}
        try:
            async with self._run_slots:
                self.repo.update_task(research_id, status=ResearchStatus.running, started_at=utcnow())
                self.repo.add_event(research_id, "started", "Research started")
                deps = self._factory(self.settings)
                config["configurable"]["ctx"] = self._context(research_id, deps)
                final = await asyncio.wait_for(
                    self._graph.ainvoke({"research_id": research_id, "request": request, "warnings": []}, config),
                    timeout=self.settings.max_research_seconds,
                )
            report = final["report"]
            quality = report.quality_assessment
            self.repo.finish_task(
                research_id,
                "completed",
                "Research completed" + (" with warnings" if report.status != ResearchStatus.completed else ""),
                {"status": report.status.value, "quality_status": quality.status},
                status=report.status,
                current_stage=None,
                warnings=list(dict.fromkeys(final.get("warnings", []))),
            )
        except asyncio.CancelledError:
            self._finish_failed(research_id, config, ResearchStatus.cancelled, "Research was cancelled.")
        except asyncio.TimeoutError:
            self._finish_failed(
                research_id, config, ResearchStatus.failed,
                f"Research exceeded the maximum run time of {int(self.settings.max_research_seconds)} seconds.",
            )
        except (WorkflowError, SearchError, LLMError) as exc:
            self._finish_failed(research_id, config, ResearchStatus.failed, str(exc))
        except Exception as exc:  # pragma: no cover - defensive catch-all, logged with traceback
            logger.exception("Research %s failed", research_id)
            self._finish_failed(
                research_id, config, ResearchStatus.failed,
                f"Unexpected error ({type(exc).__name__}). Check the backend logs for details.",
            )
        finally:
            try:
                self._graph.checkpointer.delete_thread(research_id)
            except Exception:  # pragma: no cover
                pass

    def _finish_failed(self, research_id: str, config: dict, status: ResearchStatus, message: str) -> None:
        warnings: list[str] = []
        try:
            # The checkpoint holds whatever the graph accumulated before failing.
            snapshot = self._graph.get_state(config)
            warnings = list(dict.fromkeys((snapshot.values or {}).get("warnings", [])))
        except Exception:
            pass
        event = "cancelled" if status == ResearchStatus.cancelled else "failed"
        self.repo.finish_task(
            research_id, event, message, {"status": status.value},
            status=status, error=message, warnings=warnings,
        )
