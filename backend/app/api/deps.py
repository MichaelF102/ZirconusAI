"""FastAPI dependency accessors."""

from __future__ import annotations

from fastapi import Request

from app.db.repository import ResearchRepository
from app.services.research_service import ResearchService


def get_repo(request: Request) -> ResearchRepository:
    return request.app.state.repo


def get_service(request: Request) -> ResearchService:
    return request.app.state.service
