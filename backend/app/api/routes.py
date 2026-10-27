"""REST endpoints for research tasks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.deps import get_repo, get_service
from app.db.repository import ResearchRepository
from app.schemas.evidence import SourceRecord
from app.schemas.research import (
    ResearchCreated,
    ResearchDetail,
    ResearchReport,
    ResearchRequest,
    ResearchStatus,
    ResearchSummary,
)
from app.services.research_service import ResearchService

router = APIRouter(prefix="/api/research", tags=["research"])


def _require_task(repo: ResearchRepository, research_id: str) -> ResearchDetail:
    detail = repo.get_detail(research_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Research task not found")
    return detail


@router.post("", response_model=ResearchCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_research(
    body: ResearchRequest, request: Request, service: ResearchService = Depends(get_service)
) -> ResearchCreated:
    missing = service.missing_configuration()
    if missing:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"The research backend is not configured: missing {', '.join(missing)}.",
        )
    client = request.client.host if request.client else "unknown"
    allowed, retry_after = request.app.state.create_limiter.allow(client)
    if not allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many research requests. Please wait before starting another.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
    research_id = service.start(body)
    return ResearchCreated(id=research_id, status=ResearchStatus.queued)


@router.get("", response_model=list[ResearchSummary])
def list_research(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: ResearchRepository = Depends(get_repo),
) -> list[ResearchSummary]:
    return repo.list_tasks(limit=limit, offset=offset)


@router.get("/{research_id}", response_model=ResearchDetail)
def get_research(research_id: str, repo: ResearchRepository = Depends(get_repo)) -> ResearchDetail:
    return _require_task(repo, research_id)


@router.get("/{research_id}/report", response_model=ResearchReport)
def get_report(research_id: str, repo: ResearchRepository = Depends(get_repo)) -> ResearchReport:
    detail = _require_task(repo, research_id)
    report = repo.get_report(research_id)
    if report is None:
        if detail.status in (ResearchStatus.queued, ResearchStatus.running):
            raise HTTPException(status.HTTP_409_CONFLICT, "The report is not ready yet")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No report was produced for this task")
    return report


@router.get("/{research_id}/sources", response_model=list[SourceRecord])
def get_sources(research_id: str, repo: ResearchRepository = Depends(get_repo)) -> list[SourceRecord]:
    _require_task(repo, research_id)
    return repo.get_sources(research_id)


@router.post("/{research_id}/cancel", response_model=ResearchDetail)
async def cancel_research(
    research_id: str,
    repo: ResearchRepository = Depends(get_repo),
    service: ResearchService = Depends(get_service),
) -> ResearchDetail:
    detail = _require_task(repo, research_id)
    if detail.status.is_terminal:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Research already {detail.status.value}")
    if not await service.cancel(research_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Research is not running in this server process")
    return _require_task(repo, research_id)
