"""Assembles the final Markdown report and quality assessment from validated workflow state."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from app.schemas.evidence import CriticResult, EvidenceMatrix, SourceRecord
from app.schemas.research import QualityAssessment, ResearchPlan, ResearchStatus
from app.services.citations import check_report_citations, parse_citation_ids, strip_invalid_citations

_FORBIDDEN_SECTIONS = re.compile(r"^#{1,3}\s*(references|sources|bibliography|works cited)\b.*$", re.I | re.M)


def sanitize_body(body: str) -> str:
    """Drop any references list the model wrote anyway, and demote stray H1s."""
    match = _FORBIDDEN_SECTIONS.search(body)
    if match:
        body = body[: match.start()]
    body = re.sub(r"^# (?!#)", "## ", body, flags=re.M)
    # Raw URLs are never trusted from the model; references come from source records.
    body = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", body)
    return body.strip()


def methodology_section(question: str, plan: ResearchPlan, sources: list[SourceRecord], revisions: int) -> str:
    extracted = sum(1 for s in sources if s.extraction_status == "extracted")
    snippet = sum(1 for s in sources if s.extraction_status == "snippet_only")
    failed = sum(1 for s in sources if s.extraction_status == "failed")
    domains = len({s.domain for s in sources})
    lines = [
        "## Research question and methodology",
        "",
        f"**Question:** {question}",
        "",
        f"**Objective:** {plan.objective}",
        "",
        "**Subquestions investigated:**",
        "",
        *[f"{i}. {sq.question}" for i, sq in enumerate(plan.subquestions, 1)],
        "",
        (
            f"**Process:** An automated agent searched the web for each subquestion and retrieved "
            f"{len(sources)} unique sources from {domains} domains ({extracted} with full text extracted, "
            f"{snippet} available only as search snippets, {failed} unavailable). Claims were extracted into "
            f"an evidence matrix, the draft was reviewed by a critic combining deterministic citation checks "
            f"with an LLM review, and it went through {revisions} revision cycle{'s' if revisions != 1 else ''}."
        ),
    ]
    if plan.scope:
        lines += ["", f"**Scope:** {plan.scope}"]
    return "\n".join(lines)


def references_section(sources: list[SourceRecord], cited_ids: list[str]) -> str:
    by_id = {s.source_id: s for s in sources}
    lines = ["## References", ""]
    for sid in cited_ids:
        s = by_id[sid]
        title = s.title.replace("[", "(").replace("]", ")")
        parts = [f"**[{sid}]** [{title}]({s.url}) — {s.domain}"]
        parts.append(f"Published: {s.published_at}" if s.published_at else "Publication date: not stated")
        parts.append(f"Retrieved: {s.retrieved_at.date().isoformat()}")
        if s.extraction_status != "extracted":
            parts.append("Evidence: search snippet only")
        lines.append("- " + ". ".join(parts) + ".")
    if not cited_ids:
        lines.append("_No sources were cited._")
    return "\n".join(lines)


def build_final_report(
    *,
    title: str,
    question: str,
    executive_summary: str,
    body: str,
    plan: ResearchPlan,
    sources: list[SourceRecord],
    evidence: EvidenceMatrix | None,
    critic: CriticResult | None,
    revisions: int,
) -> tuple[str, str, QualityAssessment, ResearchStatus]:
    """Validate citations and render the final document. Returns (markdown, summary, quality, status)."""
    valid_ids = {s.source_id for s in sources}
    body = sanitize_body(body)
    body, removed_body = strip_invalid_citations(body, valid_ids)
    summary, removed_summary = strip_invalid_citations(executive_summary.strip(), valid_ids)
    removed = sorted(set(removed_body + removed_summary))

    check = check_report_citations(summary + "\n\n" + body, sources)
    cited_ids = sorted(set(parse_citation_ids(summary + "\n" + body)), key=lambda x: int(x[1:]))

    markdown = "\n\n".join(
        [
            f"# {title.strip()}",
            "## Executive summary",
            summary,
            methodology_section(question, plan, sources, revisions),
            body,
            references_section(sources, cited_ids),
        ]
    )

    # Issues still standing after the last critic pass, plus anything the final deterministic check finds.
    unresolved: list[dict] = []
    seen: set[tuple[str, str]] = set()
    remaining_issues = [*(critic.issues if critic and critic.requires_revision else []), *check.issues]
    for issue in remaining_issues:
        if issue.severity == "low":
            continue
        key = (issue.type, issue.claim_text or issue.description)
        if key in seen:
            continue
        seen.add(key)
        unresolved.append(issue.model_dump())

    claims_by_subq = {c.subquestion_id for c in (evidence.claims if evidence else [])}
    missing = set(critic.missing_coverage if critic else [])
    coverage = {sq.id: (sq.id in claims_by_subq and sq.id not in missing) for sq in plan.subquestions}

    notes = []
    if removed:
        notes.append(f"Removed citations to non-existent sources: {', '.join(removed)}.")
    if check.uncited_factual:
        notes.append(f"{len(check.uncited_factual)} factual-looking sentence(s) have no citation.")
    if not all(coverage.values()):
        notes.append("Some subquestions are not fully covered by the evidence.")
    notes.append(
        "Automated checks verify that citations resolve to retrieved sources and that cited text overlaps "
        "with the claim; they do not guarantee the claims are true."
    )

    has_high = any(i["severity"] == "high" for i in unresolved)
    if check.valid_citation_count == 0:
        status = "failed"
    elif has_high:
        status = "failed"
    elif unresolved or removed or not all(coverage.values()):
        status = "passed_with_warnings"
    else:
        status = "passed"

    quality = QualityAssessment(
        status=status,
        citation_count=check.citation_count + len(removed),
        valid_citation_count=check.valid_citation_count,
        invalid_citations_removed=removed,
        cited_source_count=len(cited_ids),
        distinct_cited_domains=len({s.domain for s in sources if s.source_id in cited_ids}),
        uncited_factual_sentences=len(check.uncited_factual),
        revision_cycles=revisions,
        unresolved_issues=unresolved,
        subquestion_coverage=coverage,
        notes=notes,
    )
    task_status = ResearchStatus.completed if status == "passed" else ResearchStatus.completed_with_warnings
    return markdown, summary, quality, task_status


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
