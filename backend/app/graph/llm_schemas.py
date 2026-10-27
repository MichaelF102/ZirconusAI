"""Structured-output schemas requested from the LLM.

Kept separate from the domain models: the LLM never assigns IDs, timestamps or URLs. Those are
added (and validated) by the workflow.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PlannedSubquestion(BaseModel):
    question: str = Field(description="A focused, answerable research subquestion")
    search_queries: list[str] = Field(description="1-3 concise web search queries for this subquestion")
    evidence_needed: str = Field(description="What evidence would answer this subquestion")


class PlanOutput(BaseModel):
    objective: str = Field(description="One-sentence statement of the research objective")
    subquestions: list[PlannedSubquestion]
    search_strategy: str = Field(description="Which kinds of sources to prioritise and why")
    methodology: str = Field(description="Short description of how the question will be answered")
    scope: str = Field(description="What is in and out of scope")
    limitations: list[str] = Field(description="Known limitations of the planned research")


class ContradictionOutput(BaseModel):
    source_id: str
    text: str = Field(description="What the contradicting source says")


class ClaimOutput(BaseModel):
    claim_text: str = Field(description="A single factual claim, stated precisely")
    subquestion_id: str = Field(description="ID of the subquestion this claim addresses, e.g. Q1")
    source_ids: list[str] = Field(description="IDs of sources that directly state or support this claim")
    supporting_quotes: list[str] = Field(description="Short verbatim excerpts from the cited sources")
    contradicting: list[ContradictionOutput] = Field(description="Sources that disagree with the claim")
    assessment: Literal["established", "reported", "estimate", "interpretation", "contested", "uncertain"]
    limitations: str = Field(description="Caveats such as single-source, vendor claim, old data; empty if none")


class EvidenceOutput(BaseModel):
    claims: list[ClaimOutput]
    conflicts: list[str] = Field(description="Disagreements between sources, citing source IDs")
    gaps: list[str] = Field(description="Subquestions or aspects the sources do not adequately answer")


class DraftOutput(BaseModel):
    title: str
    executive_summary: str = Field(description="3-5 sentence summary with citations like [S1]")
    body_markdown: str = Field(description="Report body in Markdown, starting at the '## Key findings' section")


class CriticIssueOutput(BaseModel):
    type: Literal[
        "unsupported_claim", "weak_support", "invalid_citation", "missing_coverage", "contradiction",
        "overconfident", "source_quality", "outdated", "omission", "other",
    ]
    severity: Literal["low", "medium", "high"]
    claim_text: str = Field(description="The exact sentence from the draft this issue concerns, or empty")
    source_ids: list[str]
    description: str
    recommendation: str


class CriticOutput(BaseModel):
    overall_assessment: str
    issues: list[CriticIssueOutput]
    missing_subquestions: list[str] = Field(description="IDs of subquestions the draft does not adequately answer")
    requires_revision: bool
    requires_more_research: bool
    follow_up_queries: list[str] = Field(description="Targeted web search queries to fill evidence gaps (max 3)")
