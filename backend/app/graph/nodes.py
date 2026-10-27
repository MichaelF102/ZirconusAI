"""LangGraph node implementations.

Each node reads typed state, performs one research step and returns a partial state update.
Progress is reported through ``ctx.emit`` (persisted and streamed to the frontend over SSE).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from langchain_core.runnables import RunnableConfig

from app.graph.context import get_ctx
from app.graph.llm_schemas import CriticOutput, DraftOutput, EvidenceOutput, PlanOutput
from app.graph.prompts import (
    ANALYST_SYSTEM,
    CRITIC_SYSTEM,
    PLANNER_SYSTEM,
    WRITER_SYSTEM,
    analyst_prompt,
    critic_prompt,
    planner_prompt,
    writer_prompt,
)
from app.graph.state import PendingQuery, ResearchState, RevisionRecord
from app.schemas.evidence import (
    ContradictingEvidence,
    CriticIssue,
    CriticResult,
    EvidenceClaim,
    EvidenceMatrix,
    SourceRecord,
)
from app.schemas.research import ResearchPlan, ResearchReport, SubQuestion
from app.services.citations import check_report_citations, quote_in_source
from app.services.report_service import build_final_report, sanitize_body
from app.tools.extraction import ExtractionError, UnsafeURLError
from app.tools.search import SearchError, SearchHit, SearchOptions, classify_source, dedupe_hits, domain_of, normalize_url

logger = logging.getLogger(__name__)


class WorkflowError(Exception):
    """A non-recoverable failure in a workflow step, with a user-safe message."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stage(config: RunnableConfig, node: str, message: str) -> None:
    ctx = get_ctx(config)
    ctx.on_stage(node)
    ctx.emit("stage_started", node, message, None)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------
async def planner(state: ResearchState, config: RunnableConfig) -> dict:
    ctx = get_ctx(config)
    request = state["request"]
    profile = ctx.depth_profile(request.depth, request.max_sources_per_subquestion)
    _stage(config, "planner", "Breaking the question into research subquestions")

    filters = []
    if request.include_domains:
        filters.append(f"Searches will be restricted to: {', '.join(request.include_domains)}.")
    if request.start_date or request.end_date:
        filters.append(f"Sources should be published between {request.start_date or 'any'} and {request.end_date or 'now'}.")

    output = await ctx.structured(
        PlanOutput,
        PLANNER_SYSTEM,
        planner_prompt(request.question, profile.subquestions, profile.queries_per_subquestion, "\n".join(filters)),
        label="planner",
    )

    subquestions: list[SubQuestion] = []
    for item in output.subquestions[: profile.subquestions]:
        question = item.question.strip()
        if not question:
            continue
        queries = [q.strip() for q in item.search_queries if q.strip()][: profile.queries_per_subquestion]
        subquestions.append(
            SubQuestion(
                id=f"Q{len(subquestions) + 1}",
                question=question,
                search_queries=queries or [question],
                evidence_needed=item.evidence_needed,
            )
        )
    if not subquestions:
        raise WorkflowError("The planner did not produce any subquestions.")

    plan = ResearchPlan(
        objective=output.objective,
        subquestions=subquestions,
        search_strategy=output.search_strategy,
        methodology=output.methodology,
        scope=output.scope,
        limitations=output.limitations,
    )
    ctx.on_plan(plan)
    ctx.emit(
        "plan",
        "planner",
        f"Planned {len(subquestions)} subquestions",
        {"subquestions": [sq.model_dump() for sq in subquestions], "objective": plan.objective},
    )
    pending = [PendingQuery(query=q, subquestion_id=sq.id) for sq in subquestions for q in sq.search_queries]
    return {"plan": plan, "pending_queries": pending, "sources": [], "revision_count": 0, "revisions": []}


# ---------------------------------------------------------------------------
# Web researcher
# ---------------------------------------------------------------------------
def merge_search_results(
    existing: list[SourceRecord],
    results: list[tuple[PendingQuery, list[SearchHit]]],
    max_per_subquestion: int,
) -> list[SourceRecord]:
    """Deduplicate hits by normalised URL, assign stable sequential IDs and cap per subquestion."""
    sources = [s.model_copy(deep=True) for s in existing]
    by_key = {normalize_url(s.url): s for s in sources}
    next_id = max((int(s.source_id[1:]) for s in sources), default=0) + 1
    new_per_subq: dict[str, int] = {}

    for pending, hits in results:
        for hit in dedupe_hits(hits):
            key = normalize_url(hit.url)
            if key in by_key:
                src = by_key[key]
                if pending.subquestion_id not in src.subquestion_ids:
                    src.subquestion_ids.append(pending.subquestion_id)
                continue
            if new_per_subq.get(pending.subquestion_id, 0) >= max_per_subquestion:
                continue
            new_per_subq[pending.subquestion_id] = new_per_subq.get(pending.subquestion_id, 0) + 1
            src = SourceRecord(
                source_id=f"S{next_id}",
                title=hit.title[:300],
                url=hit.url,
                domain=domain_of(hit.url),
                published_at=hit.published_at,
                retrieved_at=_now(),
                snippet=hit.snippet[:2000],
                extraction_status="pending",
                source_type=classify_source(hit.url),
                search_query=pending.query,
                subquestion_ids=[pending.subquestion_id],
                search_score=hit.score,
            )
            next_id += 1
            by_key[key] = src
            sources.append(src)
    return sources


async def researcher(state: ResearchState, config: RunnableConfig) -> dict:
    ctx = get_ctx(config)
    request = state["request"]
    pending = state.get("pending_queries", [])
    profile = ctx.depth_profile(request.depth, request.max_sources_per_subquestion)
    _stage(config, "researcher", f"Running {len(pending)} web searches")

    options = SearchOptions(
        max_results=profile.sources_per_subquestion,
        include_domains=request.include_domains,
        exclude_domains=request.exclude_domains,
        start_date=request.start_date,
        end_date=request.end_date,
    )
    warnings: list[str] = []

    async def _run(pq: PendingQuery) -> tuple[PendingQuery, list[SearchHit]]:
        async with ctx.search_semaphore:
            ctx.usage.search_calls += 1
            try:
                hits = await ctx.search.search(pq.query, options)
            except SearchError as exc:
                msg = f"Search failed for '{pq.query}': {exc}"
                warnings.append(msg)
                ctx.emit("warning", "researcher", msg, {"query": pq.query})
                return pq, []
            ctx.emit(
                "search",
                "researcher",
                f"Found {len(hits)} results for '{pq.query}'",
                {"query": pq.query, "subquestion_id": pq.subquestion_id, "results": len(hits)},
            )
            return pq, hits

    results = await asyncio.gather(*[_run(pq) for pq in pending])
    ctx.on_usage(ctx.usage)
    existing = state.get("sources", [])
    sources = merge_search_results(existing, list(results), profile.sources_per_subquestion)
    added = len(sources) - len(existing)

    if not sources:
        raise WorkflowError(
            "No sources were found. " + (warnings[0] if warnings else "Try broadening the question or filters.")
        )
    ctx.on_sources(sources)
    ctx.emit("sources", "researcher", f"Collected {added} new sources ({len(sources)} total)",
             {"added": added, "total": len(sources)})
    return {"sources": sources, "pending_queries": [], "warnings": warnings}


# ---------------------------------------------------------------------------
# Source extractor
# ---------------------------------------------------------------------------
async def extractor(state: ResearchState, config: RunnableConfig) -> dict:
    ctx = get_ctx(config)
    sources = [s.model_copy(deep=True) for s in state["sources"]]
    todo = [s for s in sources if s.extraction_status == "pending"]
    _stage(config, "extractor", f"Reading {len(todo)} pages")

    async def _extract(src: SourceRecord) -> None:
        async with ctx.fetch_semaphore:
            ctx.usage.pages_fetched += 1
            try:
                result = await ctx.extractor.extract(src.url)
            except (ExtractionError, UnsafeURLError) as exc:
                reason = str(exc)
            except Exception as exc:  # malformed pages must never fail the whole run
                logger.exception("Unexpected extraction error for %s", src.url)
                reason = f"Unexpected error: {type(exc).__name__}"
            else:
                src.extracted_content = result.text
                src.extraction_status = "extracted"
                src.published_at = src.published_at or result.published_at
                if result.title and (not src.title or src.title == src.url):
                    src.title = result.title[:300]
                src.retrieved_at = _now()
                return
            ctx.usage.fetch_failures += 1
            src.extraction_error = reason
            src.extraction_status = "snippet_only" if src.snippet else "failed"
            src.retrieved_at = _now()

    await asyncio.gather(*[_extract(s) for s in todo])
    ctx.on_usage(ctx.usage)
    ctx.on_sources(sources)

    ok = sum(1 for s in todo if s.extraction_status == "extracted")
    snippet = sum(1 for s in todo if s.extraction_status == "snippet_only")
    failed = sum(1 for s in todo if s.extraction_status == "failed")
    warnings = []
    if todo and ok == 0:
        warnings.append("No pages could be fully extracted; the report relies on search snippets.")
    elif snippet + failed:
        ctx.emit("warning", "extractor", f"{snippet + failed} page(s) could not be extracted",
                 {"snippet_only": snippet, "failed": failed})
    ctx.emit("extraction", "extractor", f"Extracted {ok} pages; {snippet} snippet-only; {failed} failed",
             {"extracted": ok, "snippet_only": snippet, "failed": failed})
    if not any(s.evidence_text for s in sources):
        raise WorkflowError("None of the retrieved sources contained usable text.")
    return {"sources": sources, "warnings": warnings}


# ---------------------------------------------------------------------------
# Evidence analyst
# ---------------------------------------------------------------------------
def validate_evidence(output: EvidenceOutput, sources: list[SourceRecord], plan: ResearchPlan) -> EvidenceMatrix:
    """Keep only claims grounded in known sources, and only quotes that appear in those sources."""
    by_id = {s.source_id: s for s in sources if s.evidence_text}
    subq_ids = {sq.id for sq in plan.subquestions}
    claims: list[EvidenceClaim] = []
    dropped = 0
    for item in output.claims:
        source_ids = list(dict.fromkeys(sid.strip() for sid in item.source_ids if sid.strip() in by_id))
        if not source_ids or not item.claim_text.strip():
            dropped += 1
            continue
        evidence_text = "\n".join(by_id[sid].evidence_text for sid in source_ids)
        quotes = [q.strip() for q in item.supporting_quotes if q.strip() and quote_in_source(q, evidence_text)]
        limitations = item.limitations.strip()
        if item.supporting_quotes and not quotes:
            limitations = (limitations + " " if limitations else "") + "Quoted excerpts could not be located verbatim in the source."
        if len({by_id[sid].domain for sid in source_ids}) == 1 and len(source_ids) > 1:
            limitations = (limitations + " " if limitations else "") + "All supporting sources share one domain."
        contradictions = [
            ContradictingEvidence(source_id=c.source_id, text=c.text)
            for c in item.contradicting
            if c.source_id in by_id
        ]
        claims.append(
            EvidenceClaim(
                claim_id=f"C{len(claims) + 1}",
                claim_text=item.claim_text.strip(),
                subquestion_id=item.subquestion_id if item.subquestion_id in subq_ids else None,
                source_ids=source_ids,
                supporting_evidence=quotes,
                contradicting_evidence=contradictions,
                assessment="contested" if contradictions and item.assessment == "established" else item.assessment,
                limitations=limitations,
            )
        )
    return EvidenceMatrix(claims=claims, conflicts=output.conflicts, gaps=output.gaps, dropped_claims=dropped)


async def analyst(state: ResearchState, config: RunnableConfig) -> dict:
    ctx = get_ctx(config)
    sources = state["sources"]
    plan = state["plan"]
    _stage(config, "analyst", "Comparing sources and building the evidence matrix")
    output = await ctx.structured(
        EvidenceOutput, ANALYST_SYSTEM, analyst_prompt(state["request"].question, plan, sources), label="analyst"
    )
    matrix = validate_evidence(output, sources, plan)
    if not matrix.claims:
        raise WorkflowError("The evidence analyst could not ground any claims in the retrieved sources.")
    warnings = []
    if matrix.dropped_claims:
        warnings.append(f"{matrix.dropped_claims} claim(s) were discarded because they cited unknown sources.")
    ctx.emit(
        "evidence",
        "analyst",
        f"Grounded {len(matrix.claims)} claims; {len(matrix.conflicts)} conflicts; {len(matrix.gaps)} gaps",
        {"claims": len(matrix.claims), "conflicts": len(matrix.conflicts), "gaps": matrix.gaps[:5],
         "dropped": matrix.dropped_claims},
    )
    return {"evidence": matrix, "warnings": warnings}


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------
async def writer(state: ResearchState, config: RunnableConfig) -> dict:
    ctx = get_ctx(config)
    revision = state.get("revision_count", 0)
    previous = state.get("draft")
    critic = state.get("critic")
    is_revision = revision > 0 and previous is not None and critic is not None
    _stage(config, "writer", "Revising the report" if is_revision else "Writing the cited report")

    prompt = writer_prompt(
        state["request"].question,
        state["plan"],
        state["evidence"],
        state["sources"],
        previous_body=previous.body_markdown if is_revision else None,
        issues=critic.issues if is_revision else None,
    )
    draft = await ctx.structured(DraftOutput, WRITER_SYSTEM, prompt, label="writer")
    draft = DraftOutput(
        title=draft.title.strip() or state["request"].question,
        executive_summary=draft.executive_summary.strip(),
        body_markdown=sanitize_body(draft.body_markdown),
    )
    ctx.emit("draft", "writer", f"Draft {'revision ' + str(revision) if is_revision else '1'} written",
             {"revision": revision, "length": len(draft.body_markdown)})
    return {"draft": draft}


# ---------------------------------------------------------------------------
# Critic
# ---------------------------------------------------------------------------
def combine_critic(
    deterministic: list[CriticIssue],
    llm: CriticOutput | None,
    invalid_ids: list[str],
    uncited: list[str],
    valid_subq_ids: set[str],
    valid_source_ids: set[str],
) -> CriticResult:
    """Merge deterministic and LLM findings. The LLM can add issues but cannot clear deterministic ones."""
    issues = list(deterministic)
    missing: list[str] = []
    follow_ups: list[str] = []
    llm_requires_revision = False
    llm_requires_research = False
    assessment = ""
    if llm is not None:
        assessment = llm.overall_assessment
        for item in llm.issues:
            issues.append(
                CriticIssue(
                    type=item.type,
                    severity=item.severity,
                    description=item.description,
                    claim_text=item.claim_text,
                    source_ids=[s for s in item.source_ids if s in valid_source_ids],
                    recommendation=item.recommendation,
                    origin="llm",
                )
            )
        missing = [q for q in llm.missing_subquestions if q in valid_subq_ids]
        follow_ups = [q.strip() for q in llm.follow_up_queries if q.strip()][:3]
        llm_requires_revision = llm.requires_revision
        llm_requires_research = llm.requires_more_research

    high = sum(1 for i in issues if i.severity == "high")
    medium = sum(1 for i in issues if i.severity == "medium")
    requires_revision = bool(high or invalid_ids or missing or medium >= 2 or llm_requires_revision)
    requires_research = bool(requires_revision and (llm_requires_research or missing) and follow_ups)

    summary = (
        f"{high} high, {medium} medium and {len(issues) - high - medium} low severity issues; "
        f"{len(invalid_ids)} invalid citation(s); {len(uncited)} uncited factual sentence(s)."
    )
    return CriticResult(
        overall_assessment=assessment or ("No material issues found." if not requires_revision else summary),
        issues=issues,
        unsupported_claims=[i.claim_text for i in issues if i.type == "unsupported_claim" and i.claim_text],
        invalid_citations=invalid_ids,
        missing_coverage=missing,
        requires_revision=requires_revision,
        requires_more_research=requires_research,
        follow_up_queries=follow_ups if requires_research else [],
        summary=summary,
    )


async def critic(state: ResearchState, config: RunnableConfig) -> dict:
    ctx = get_ctx(config)
    draft = state["draft"]
    sources = state["sources"]
    plan = state["plan"]
    _stage(config, "critic", "Checking claims and citations against the evidence")

    full_text = f"## Executive summary\n\n{draft.executive_summary}\n\n{draft.body_markdown}"
    check = check_report_citations(full_text, sources)
    warnings: list[str] = []
    llm_output: CriticOutput | None = None
    try:
        llm_output = await ctx.structured(
            CriticOutput,
            CRITIC_SYSTEM,
            critic_prompt(state["request"].question, plan, state["evidence"], sources, full_text, check.issues),
            label="critic",
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("LLM critic failed: %s", exc)
        warnings.append("The LLM critic was unavailable for one pass; only deterministic checks were applied.")
        ctx.emit("warning", "critic", "LLM review unavailable; applied deterministic checks only", None)

    result = combine_critic(
        check.issues,
        llm_output,
        check.invalid_ids,
        check.uncited_factual,
        {sq.id for sq in plan.subquestions},
        {s.source_id for s in sources},
    )
    ctx.emit(
        "critic",
        "critic",
        ("Revision required: " if result.requires_revision else "Passed: ") + result.summary,
        {
            "requires_revision": result.requires_revision,
            "requires_more_research": result.requires_more_research,
            "issues": [i.model_dump() for i in result.issues[:20]],
            "revision_count": state.get("revision_count", 0),
        },
    )
    return {"critic": result, "warnings": warnings}


# ---------------------------------------------------------------------------
# Revision router (node part: bookkeeping + follow-up research queue)
# ---------------------------------------------------------------------------
async def revise(state: ResearchState, config: RunnableConfig) -> dict:
    ctx = get_ctx(config)
    critic_result = state["critic"]
    cycle = state.get("revision_count", 0) + 1
    ctx.on_revision(cycle)
    _stage(config, "revise", f"Starting revision cycle {cycle}")

    pending: list[PendingQuery] = []
    if critic_result.requires_more_research:
        # Attach follow-up queries to the first subquestion flagged as missing, else the first one.
        target = (critic_result.missing_coverage or [state["plan"].subquestions[0].id])[0]
        pending = [PendingQuery(query=q, subquestion_id=target) for q in critic_result.follow_up_queries]

    record = RevisionRecord(
        cycle=cycle,
        reason=critic_result.summary,
        material_issues=len(critic_result.material_issues),
        follow_up_queries=[p.query for p in pending],
    )
    ctx.emit(
        "revision",
        "revise",
        f"Revision {cycle}: " + ("researching evidence gaps" if pending else "rewriting to fix critic issues"),
        record.model_dump(),
    )
    return {"revision_count": cycle, "pending_queries": pending, "revisions": [*state.get("revisions", []), record]}


# ---------------------------------------------------------------------------
# Finalizer
# ---------------------------------------------------------------------------
async def finalizer(state: ResearchState, config: RunnableConfig) -> dict:
    ctx = get_ctx(config)
    _stage(config, "finalizer", "Validating citations and saving the report")
    draft = state["draft"]
    critic_result = state.get("critic")
    revisions = state.get("revision_count", 0)
    markdown, summary, quality, status = build_final_report(
        title=draft.title,
        question=state["request"].question,
        executive_summary=draft.executive_summary,
        body=draft.body_markdown,
        plan=state["plan"],
        sources=state["sources"],
        evidence=state.get("evidence"),
        critic=critic_result,
        revisions=revisions,
    )
    if critic_result and critic_result.requires_revision:
        quality.notes.insert(
            0,
            f"The revision limit ({ctx.settings.max_revision_cycles}) was reached with issues still open; "
            "this is the best available report.",
        )
    report = ResearchReport(
        research_id=state["research_id"],
        title=draft.title,
        question=state["request"].question,
        status=status,
        executive_summary=summary,
        report_markdown=markdown,
        sources=state["sources"],
        evidence_matrix=state.get("evidence"),
        critic=critic_result,
        quality_assessment=quality,
        plan=state["plan"],
        created_at=_now(),
        completed_at=_now(),
    )
    ctx.on_report(report)
    ctx.emit(
        "quality",
        "finalizer",
        f"Quality check: {quality.status.replace('_', ' ')}; {quality.valid_citation_count}/{quality.citation_count} "
        f"citations valid",
        {"quality_status": quality.status, "unresolved": len(quality.unresolved_issues)},
    )
    return {"report": report}
