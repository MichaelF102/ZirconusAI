import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.graph.nodes import WorkflowError
from app.graph.workflow import build_workflow
from app.schemas.research import ResearchRequest, ResearchStatus
from app.tools.llm import LLMError
from tests.fakes import (
    BAD_BODY,
    FakeSearch,
    critic_needs_research,
    critic_ok,
    default_llm,
    make_draft,
)

REQUEST = ResearchRequest(question="How is agentic AI changing data engineering?")


async def _run(ctx, thread="t1"):
    graph = build_workflow(InMemorySaver())
    config = {"configurable": {"thread_id": thread, "ctx": ctx}, "recursion_limit": 50}
    return await graph.ainvoke({"research_id": "r1", "request": REQUEST, "warnings": []}, config)


async def test_happy_path_produces_validated_report(make_ctx):
    events = []
    reports = []
    ctx = make_ctx(events=events, on_report=reports.append)
    final = await _run(ctx)
    report = final["report"]
    assert report.status == ResearchStatus.completed
    assert report.quality_assessment.status == "passed"
    assert report.quality_assessment.citation_validity == 1.0
    assert final["revision_count"] == 0
    md = report.report_markdown
    for heading in ["## Executive summary", "## Research question and methodology", "## Key findings",
                    "## Limitations and uncertainty", "## Conclusion", "## References"]:
        assert heading in md
    assert "[LangGraph persistence](https://docs.langchain.com/langgraph/persistence)" in md
    assert reports == [report]
    stages = [e[1] for e in events if e[0] == "stage_started"]
    assert stages == ["planner", "researcher", "extractor", "analyst", "writer", "critic", "finalizer"]
    assert ctx.usage.llm_calls == 4


async def test_revision_fixes_bad_draft(make_ctx):
    llm = default_llm(draft=[make_draft(BAD_BODY), make_draft()])
    final = await _run(make_ctx(llm=llm))
    assert final["revision_count"] == 1
    assert final["report"].status == ResearchStatus.completed
    # The revision prompt carries the critic's deterministic findings.
    revision_prompt = llm.prompts["DraftOutput"][1]
    assert "S9" in revision_prompt and "REVISION" in revision_prompt


async def test_revision_limit_is_enforced_and_best_report_returned(make_ctx, settings):
    llm = default_llm(draft=[make_draft(BAD_BODY)])  # writer never fixes the problems
    events = []
    final = await _run(make_ctx(llm=llm, events=events))
    assert final["revision_count"] == settings.max_revision_cycles == 2
    assert len(llm.prompts["DraftOutput"]) == 3
    report = final["report"]
    assert report.status == ResearchStatus.completed_with_warnings
    q = report.quality_assessment
    assert q.invalid_citations_removed == ["S9"]
    assert "[S9]" not in report.report_markdown
    assert any("revision limit" in n for n in q.notes)
    assert q.unresolved_issues


async def test_zero_revision_budget_goes_straight_to_finalizer(make_ctx, settings):
    tight = settings.model_copy(update={"max_revision_cycles": 0})
    llm = default_llm(draft=[make_draft(BAD_BODY)])
    final = await _run(make_ctx(llm=llm, settings=tight))
    assert final["revision_count"] == 0
    assert len(llm.prompts["DraftOutput"]) == 1


async def test_gap_research_adds_sources_before_rewrite(make_ctx):
    search = FakeSearch(results={"data pipeline agent governance risks": ["https://blocked.example.com/paywalled"]})
    llm = default_llm(critic=[critic_needs_research(), critic_ok()])
    final = await _run(make_ctx(llm=llm, search=search))
    assert final["revision_count"] == 1
    assert "data pipeline agent governance risks" in [q for q, _ in search.calls]
    assert final["sources"][-1].source_id == "S4"
    assert len(llm.prompts["EvidenceOutput"]) == 2


async def test_llm_critic_outage_falls_back_to_deterministic_checks(make_ctx):
    llm = default_llm(critic=[LLMError("quota exhausted")])
    final = await _run(make_ctx(llm=llm))
    assert final["report"].status == ResearchStatus.completed
    assert any("deterministic" in w for w in final["warnings"])


async def test_failed_workflow_raises_useful_error(make_ctx):
    with pytest.raises(WorkflowError, match="No sources were found"):
        await _run(make_ctx(search=FakeSearch(empty=True)))


async def test_planner_llm_failure_propagates(make_ctx):
    with pytest.raises(LLMError):
        await _run(make_ctx(llm=default_llm(plan=[LLMError("bad json")])))


async def test_llm_timeout_is_enforced(make_ctx, settings):
    class Slow:
        name = "slow"

        async def generate(self, schema, system, prompt):
            await asyncio.sleep(5)

    fast = settings.model_copy(update={"llm_timeout_seconds": 0.05})
    with pytest.raises(asyncio.TimeoutError):
        await _run(make_ctx(llm=Slow(), settings=fast))
