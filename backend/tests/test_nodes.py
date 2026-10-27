import pytest

from app.graph import nodes
from app.graph.llm_schemas import CriticIssueOutput, CriticOutput, PlannedSubquestion, PlanOutput
from app.graph.nodes import WorkflowError, combine_critic, validate_evidence
from app.schemas.evidence import CriticIssue
from app.schemas.research import ResearchRequest
from tests.fakes import FakeExtractor, FakeSearch, critic_ok, default_llm, make_evidence, make_plan

REQUEST = ResearchRequest(question="How is agentic AI changing data engineering?")


def _config(ctx):
    return {"configurable": {"ctx": ctx}}


async def test_planner_returns_valid_structured_plan(make_ctx):
    many = make_plan(3).model_copy(update={"subquestions": make_plan(3).subquestions * 2})
    events = []
    ctx = make_ctx(llm=default_llm(plan=[many]), events=events)
    out = await nodes.planner({"request": REQUEST}, _config(ctx))
    plan = out["plan"]
    assert [sq.id for sq in plan.subquestions] == ["Q1", "Q2"]  # capped at max_subquestions
    assert all(sq.search_queries for sq in plan.subquestions)
    assert [p.subquestion_id for p in out["pending_queries"]] == ["Q1", "Q1", "Q2"]
    assert any(e[0] == "plan" for e in events)


async def test_planner_falls_back_to_question_when_no_queries(make_ctx):
    plan = PlanOutput(objective="o", subquestions=[PlannedSubquestion(question="What is X?", search_queries=[],
                      evidence_needed="")], search_strategy="", methodology="", scope="", limitations=[])
    out = await nodes.planner({"request": REQUEST}, _config(make_ctx(llm=default_llm(plan=[plan]))))
    assert out["plan"].subquestions[0].search_queries == ["What is X?"]


async def test_planner_with_no_subquestions_fails(make_ctx):
    empty = make_plan().model_copy(update={"subquestions": []})
    with pytest.raises(WorkflowError):
        await nodes.planner({"request": REQUEST}, _config(make_ctx(llm=default_llm(plan=[empty]))))


async def _plan_and_search(ctx):
    state = {"request": REQUEST}
    state.update(await nodes.planner(state, _config(ctx)))
    state.update(await nodes.researcher(state, _config(ctx)))
    return state


async def test_researcher_normalizes_and_deduplicates(make_ctx):
    search = FakeSearch()
    state = await _plan_and_search(make_ctx(search=search))
    urls = [s.url for s in state["sources"]]
    assert len(urls) == len(set(urls)) == 3
    assert [s.source_id for s in state["sources"]] == ["S1", "S2", "S3"]
    assert len(search.calls) == 3
    assert search.calls[0][1].max_results == 3


async def test_researcher_survives_partial_search_failure(make_ctx):
    events = []
    ctx = make_ctx(search=FakeSearch(fail_queries={"langgraph state"}), events=events)
    state = await _plan_and_search(ctx)
    assert state["sources"]
    assert any("simulated outage" in w for w in state["warnings"])
    assert any(e[0] == "warning" for e in events)


async def test_researcher_with_no_results_raises(make_ctx):
    with pytest.raises(WorkflowError, match="No sources"):
        await _plan_and_search(make_ctx(search=FakeSearch(empty=True)))


async def test_extraction_failures_fall_back_to_snippets(make_ctx):
    results = {q: ["https://blocked.example.com/paywalled", "https://docs.langchain.com/langgraph/persistence"]
               for q in ["langgraph persistence checkpointer", "langgraph state", "data engineering AI agents survey 2025"]}
    ctx = make_ctx(search=FakeSearch(results=results), extractor=FakeExtractor())
    state = await _plan_and_search(ctx)
    state.update(await nodes.extractor(state, _config(ctx)))
    by_url = {s.url: s for s in state["sources"]}
    blocked = by_url["https://blocked.example.com/paywalled"]
    assert blocked.extraction_status == "snippet_only"
    assert blocked.extraction_error == "HTTP 403"
    assert blocked.evidence_text == blocked.snippet
    assert by_url["https://docs.langchain.com/langgraph/persistence"].extraction_status == "extracted"
    assert ctx.usage.fetch_failures == 1


async def test_extractor_handles_unexpected_exceptions(make_ctx):
    class Broken:
        async def extract(self, url):
            raise RuntimeError("parser exploded")

    ctx = make_ctx(extractor=Broken())
    state = await _plan_and_search(ctx)
    state.update(await nodes.extractor(state, _config(ctx)))
    assert {s.extraction_status for s in state["sources"]} == {"snippet_only"}
    assert any("snippet" in w for w in state["warnings"])


async def test_evidence_claims_reference_only_known_sources(make_ctx):
    ctx = make_ctx()
    state = await _plan_and_search(ctx)
    state.update(await nodes.extractor(state, _config(ctx)))
    matrix = validate_evidence(make_evidence(), state["sources"], state["plan"])
    known = {s.source_id for s in state["sources"]}
    assert all(set(c.source_ids) <= known for c in matrix.claims)
    assert matrix.dropped_claims == 1  # the claim citing only S42
    vendor = next(c for c in matrix.claims if "Vendor" in c.claim_text)
    assert vendor.source_ids == ["S3"]  # unknown S99 removed
    assert vendor.supporting_evidence == []  # fabricated quote rejected
    assert "could not be located" in vendor.limitations
    assert matrix.claims[0].supporting_evidence  # real quote kept


def test_llm_critic_cannot_clear_deterministic_issues():
    det = [CriticIssue(type="invalid_citation", severity="high", description="S9 missing", origin="deterministic")]
    result = combine_critic(det, critic_ok(), ["S9"], [], {"Q1"}, {"S1"})
    assert result.requires_revision is True
    assert result.invalid_citations == ["S9"]


def test_critic_requires_research_only_with_follow_up_queries():
    llm = CriticOutput(
        overall_assessment="gaps", missing_subquestions=["Q2", "Q99"], requires_revision=True,
        requires_more_research=True, follow_up_queries=["a", "b", "c", "d"],
        issues=[CriticIssueOutput(type="missing_coverage", severity="medium", claim_text="", source_ids=["S1", "S77"],
                                  description="d", recommendation="r")],
    )
    result = combine_critic([], llm, [], [], {"Q1", "Q2"}, {"S1"})
    assert result.missing_coverage == ["Q2"]
    assert result.follow_up_queries == ["a", "b", "c"]
    assert result.issues[0].source_ids == ["S1"]
    assert result.requires_more_research
    no_queries = combine_critic([], llm.model_copy(update={"follow_up_queries": []}), [], [], {"Q2"}, {"S1"})
    assert no_queries.requires_revision and not no_queries.requires_more_research


def test_clean_draft_passes_critic():
    result = combine_critic([], critic_ok(), [], [], {"Q1"}, {"S1"})
    assert not result.requires_revision
