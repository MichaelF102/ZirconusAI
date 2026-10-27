"""Schemas for sources, evidence and critic output."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ExtractionStatus = Literal["pending", "extracted", "snippet_only", "failed"]
SourceType = Literal["official", "documentation", "academic", "news", "reference", "blog", "other"]
Assessment = Literal["established", "reported", "estimate", "interpretation", "contested", "uncertain"]
Severity = Literal["low", "medium", "high"]


class SourceRecord(BaseModel):
    source_id: str
    title: str
    url: str
    domain: str
    published_at: str | None = None
    retrieved_at: datetime
    snippet: str = ""
    extracted_content: str = ""
    extraction_status: ExtractionStatus = "pending"
    extraction_error: str | None = None
    source_type: SourceType = "other"
    search_query: str = ""
    subquestion_ids: list[str] = Field(default_factory=list)
    search_score: float | None = None

    @property
    def evidence_text(self) -> str:
        return self.extracted_content or self.snippet


class ContradictingEvidence(BaseModel):
    source_id: str
    text: str


class EvidenceClaim(BaseModel):
    claim_id: str
    claim_text: str
    subquestion_id: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(
        default_factory=list, description="Short excerpts quoted from the cited sources"
    )
    contradicting_evidence: list[ContradictingEvidence] = Field(default_factory=list)
    assessment: Assessment = "reported"
    limitations: str = ""


class EvidenceMatrix(BaseModel):
    claims: list[EvidenceClaim] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    dropped_claims: int = 0


class CriticIssue(BaseModel):
    type: Literal[
        "unsupported_claim",
        "weak_support",
        "invalid_citation",
        "missing_coverage",
        "contradiction",
        "overconfident",
        "source_quality",
        "outdated",
        "omission",
        "other",
    ]
    severity: Severity
    description: str
    claim_text: str = ""
    source_ids: list[str] = Field(default_factory=list)
    recommendation: str = ""
    origin: Literal["deterministic", "llm"] = "llm"


class CriticResult(BaseModel):
    overall_assessment: str = ""
    issues: list[CriticIssue] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    invalid_citations: list[str] = Field(default_factory=list)
    missing_coverage: list[str] = Field(default_factory=list)
    requires_revision: bool = False
    requires_more_research: bool = False
    follow_up_queries: list[str] = Field(default_factory=list)
    summary: str = ""

    @property
    def material_issues(self) -> list[CriticIssue]:
        return [i for i in self.issues if i.severity in ("medium", "high")]
