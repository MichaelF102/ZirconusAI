"""API-facing schemas for research tasks, plans and reports."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.evidence import CriticResult, EvidenceMatrix, SourceRecord

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

ResearchDepth = Literal["quick", "standard", "deep"]


class ResearchStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    completed_with_warnings = "completed_with_warnings"
    failed = "failed"
    cancelled = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            ResearchStatus.completed,
            ResearchStatus.completed_with_warnings,
            ResearchStatus.failed,
            ResearchStatus.cancelled,
        }


class ResearchRequest(BaseModel):
    question: str = Field(min_length=10, max_length=500)
    depth: ResearchDepth = "standard"
    include_domains: list[str] = Field(default_factory=list, max_length=10)
    exclude_domains: list[str] = Field(default_factory=list, max_length=10)
    start_date: date | None = None
    end_date: date | None = None
    max_sources_per_subquestion: int | None = Field(default=None, ge=1, le=10)

    @field_validator("question")
    @classmethod
    def _clean_question(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 10:
            raise ValueError("Question must be at least 10 characters long")
        if len(re.findall(r"[A-Za-z]", value)) < 5:
            raise ValueError("Question must contain words")
        return value

    @field_validator("include_domains", "exclude_domains")
    @classmethod
    def _validate_domains(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for raw in values:
            domain = raw.strip().lower()
            domain = re.sub(r"^https?://", "", domain).split("/")[0]
            if domain.startswith("www."):
                domain = domain[4:]
            if not domain:
                continue
            if not _DOMAIN_RE.match(domain):
                raise ValueError(f"Invalid domain: {raw!r}")
            if domain not in cleaned:
                cleaned.append(domain)
        return cleaned

    @model_validator(mode="after")
    def _check_dates(self) -> "ResearchRequest":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be before end_date")
        return self


class SubQuestion(BaseModel):
    id: str = Field(description="Stable identifier such as Q1, Q2")
    question: str
    search_queries: list[str] = Field(default_factory=list)
    evidence_needed: str = ""


class ResearchPlan(BaseModel):
    objective: str
    subquestions: list[SubQuestion]
    search_strategy: str = ""
    methodology: str = ""
    scope: str = ""
    limitations: list[str] = Field(default_factory=list)


class UsageStats(BaseModel):
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    search_calls: int = 0
    pages_fetched: int = 0
    fetch_failures: int = 0


class QualityAssessment(BaseModel):
    status: Literal["passed", "passed_with_warnings", "failed"]
    citation_count: int
    valid_citation_count: int
    invalid_citations_removed: list[str] = Field(default_factory=list)
    cited_source_count: int
    distinct_cited_domains: int
    uncited_factual_sentences: int
    revision_cycles: int
    unresolved_issues: list[dict[str, Any]] = Field(default_factory=list)
    subquestion_coverage: dict[str, bool] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    @property
    def citation_validity(self) -> float:
        return 1.0 if self.citation_count == 0 else self.valid_citation_count / self.citation_count


class ResearchReport(BaseModel):
    research_id: str
    title: str
    question: str
    status: ResearchStatus
    executive_summary: str
    report_markdown: str
    sources: list[SourceRecord]
    evidence_matrix: EvidenceMatrix | None = None
    critic: CriticResult | None = None
    quality_assessment: QualityAssessment
    plan: ResearchPlan | None = None
    created_at: datetime
    completed_at: datetime


class ResearchSummary(BaseModel):
    id: str
    question: str
    title: str | None = None
    status: ResearchStatus
    depth: str
    current_stage: str | None = None
    source_count: int = 0
    revision_count: int = 0
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class ResearchDetail(ResearchSummary):
    request: ResearchRequest
    plan: ResearchPlan | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    usage: UsageStats = Field(default_factory=UsageStats)
    elapsed_seconds: float | None = None
    has_report: bool = False


class ResearchCreated(BaseModel):
    id: str
    status: ResearchStatus


class ProgressEvent(BaseModel):
    id: int
    research_id: str
    type: str
    node: str | None = None
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime
