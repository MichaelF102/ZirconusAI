"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import events, routes
from app.api.rate_limit import SlidingWindowLimiter
from app.config import Settings, get_settings
from app.db.repository import ResearchRepository
from app.db.session import Database
from app.logging_config import configure_logging
from app.services.research_service import DependencyFactory, ResearchService, default_dependencies

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    dependency_factory: DependencyFactory | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, [settings.gemini_api_key, settings.tavily_api_key])

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db = Database(settings.database_url)
        db.create_all()
        repo = ResearchRepository(db)
        interrupted = repo.mark_interrupted_tasks()
        if interrupted:
            logger.warning("Marked %d interrupted research task(s) as failed", interrupted)
        service = ResearchService(
            repo,
            settings,
            dependency_factory or default_dependencies,
            requires_credentials=dependency_factory is None,
        )
        missing = service.missing_configuration()
        if missing:
            logger.warning("Missing configuration: %s. Research requests will be rejected.", ", ".join(missing))
        app.state.repo = repo
        app.state.service = service
        app.state.settings = settings
        app.state.create_limiter = SlidingWindowLimiter(settings.create_rate_limit_per_minute)
        yield
        await service.shutdown()
        db.engine.dispose()

    app = FastAPI(
        title="ZirconusAI API",
        version="0.1.0",
        description="Plans, searches, verifies and reports on research questions with validated citations.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_request: Request, exc: RequestValidationError):
        errors = [
            {"field": ".".join(str(p) for p in err["loc"] if p != "body"), "message": err["msg"]}
            for err in exc.errors()
        ]
        message = "; ".join(f"{e['field']}: {e['message']}" if e["field"] else e["message"] for e in errors)
        return JSONResponse(status_code=422, content={"detail": message, "errors": errors})

    @app.get("/health", tags=["health"])
    def health(request: Request):
        service: ResearchService = request.app.state.service
        missing = service.missing_configuration()
        return {
            "status": "ok" if not missing else "degraded",
            "missing_configuration": missing,
            "model": settings.gemini_model,
        }

    app.include_router(routes.router)
    app.include_router(events.router)
    return app


app = create_app()
