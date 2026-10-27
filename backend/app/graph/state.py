"""Typed state shared by LangGraph nodes."""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel

from app.graph.llm_schemas import DraftOutput
from app.schemas.evidence import CriticResult, EvidenceMatrix, SourceRecord
from app.schemas.research import ResearchPlan, ResearchReport, ResearchRequest


class PendingQuery(BaseModel):
    query: str
    subquestion_id: str


class RevisionRecord(BaseModel):
    cycle: int
    reason: str
    material_issues: int
    follow_up_queries: list[str]


class ResearchState(TypedDict, total=False):
    research_id: str
    request: ResearchRequest
    plan: ResearchPlan
    pending_queries: list[PendingQuery]
    sources: list[SourceRecord]
    evidence: EvidenceMatrix
    draft: DraftOutput
    critic: CriticResult
    revision_count: int
    revisions: list[RevisionRecord]
    warnings: Annotated[list[str], operator.add]
    report: ResearchReport
