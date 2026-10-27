"""Deterministic test doubles for the LLM, search provider and page extractor."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.graph.llm_schemas import (
    ClaimOutput,
    CriticIssueOutput,
    CriticOutput,
    DraftOutput,
    EvidenceOutput,
    PlannedSubquestion,
    PlanOutput,
)
from app.tools.extraction import ExtractionError, ExtractionResult
from app.tools.search import SearchError, SearchHit, SearchOptions

# ---------------------------------------------------------------------------
# Fixture corpus
# ---------------------------------------------------------------------------
PAGES: dict[str, dict[str, str]] = {
    "https://docs.langchain.com/langgraph/persistence": {
        "title": "LangGraph persistence",
        "snippet": "LangGraph has a built-in persistence layer implemented through checkpointers.",
        "text": (
            "LangGraph has a built-in persistence layer implemented through checkpointers. When you compile a "
            "graph with a checkpointer, the checkpointer saves a checkpoint of the graph state at every super-step. "
            "Those checkpoints are saved to a thread, which can be accessed after graph execution. Persistence "
            "enables human-in-the-loop workflows, memory between interactions, time travel and fault tolerance."
        ),
    },
    "https://www.example-survey.org/2025-data-teams": {
        "title": "2025 survey of data engineering teams",
        "snippet": "62 percent of the 400 surveyed data teams reported piloting AI agents in 2025.",
        "text": (
            "In our 2025 survey of 400 data engineering teams, 62 percent reported piloting AI agents for pipeline "
            "maintenance. Respondents most often cited automated data quality checks and schema migration as "
            "early use cases. Only 18 percent had deployed agents in production, citing reliability concerns and "
            "governance requirements as the main barriers to adoption."
        ),
    },
    "https://news.example.com/agents-data-pipelines": {
        "title": "Agents arrive in the data stack",
        "snippet": "Vendors claim agentic tools reduce pipeline maintenance time, but independent evidence is limited.",
        "text": (
            "Several vendors claim that agentic tools reduce pipeline maintenance time by up to 40 percent, but "
            "independent evidence for these figures is limited. Analysts interviewed for this article cautioned "
            "that agent reliability, observability and data governance remain open problems for production data "
            "pipelines, and recommended human review of agent-generated changes."
        ),
    },
    "https://blocked.example.com/paywalled": {
        "title": "Paywalled analyst report",
        "snippet": "An analyst firm forecasts rapid growth of agentic data tooling through 2028.",
        "text": "",
    },
}

URLS = list(PAGES)


class FakeSearch:
    name = "fake"

    def __init__(self, fail_queries: set[str] | None = None, empty: bool = False,
                 results: dict[str, list[str]] | None = None):
        self.fail_queries = fail_queries or set()
        self.empty = empty
        self.results = results
        self.calls: list[tuple[str, SearchOptions]] = []

    async def search(self, query: str, options: SearchOptions) -> list[SearchHit]:
        self.calls.append((query, options))
        if query in self.fail_queries:
            raise SearchError("simulated outage")
        if self.empty:
            return []
        urls = self.results.get(query, URLS) if self.results else URLS
        return [
            SearchHit(title=PAGES[u]["title"], url=u, snippet=PAGES[u]["snippet"], score=0.9 - i * 0.1)
            for i, u in enumerate(urls[: options.max_results])
        ]


class FakeExtractor:
    def __init__(self, fail_urls: set[str] | None = None):
        self.fail_urls = fail_urls if fail_urls is not None else {"https://blocked.example.com/paywalled"}
        self.calls: list[str] = []

    async def extract(self, url: str) -> ExtractionResult:
        self.calls.append(url)
        page = PAGES.get(url)
        if page is None or url in self.fail_urls or not page["text"]:
            raise ExtractionError("HTTP 403")
        return ExtractionResult(text=page["text"], final_url=url, title=page["title"])


# ---------------------------------------------------------------------------
# Scripted LLM
# ---------------------------------------------------------------------------
Responder = BaseModel | Callable[[str], BaseModel] | Exception


class ScriptedLLM:
    """Returns queued responses per output schema. The last response for a schema is reused."""

    name = "scripted"

    def __init__(self, responses: dict[type[BaseModel], list[Responder]]):
        self.responses = {k: list(v) for k, v in responses.items()}
        self.prompts: dict[str, list[str]] = {}

    async def generate(self, schema: type[BaseModel], system: str, prompt: str) -> tuple[Any, dict[str, int]]:
        self.prompts.setdefault(schema.__name__, []).append(prompt)
        queue = self.responses.get(schema)
        if not queue:
            raise AssertionError(f"No scripted response for {schema.__name__}")
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        result = item(prompt) if callable(item) and not isinstance(item, BaseModel) else item
        return result, {"input_tokens": len(prompt) // 4, "output_tokens": 100}


def make_plan(n: int = 2) -> PlanOutput:
    subqs = [
        PlannedSubquestion(
            question="How does LangGraph support stateful agent workflows?",
            search_queries=["langgraph persistence checkpointer", "langgraph state"],
            evidence_needed="Official documentation",
        ),
        PlannedSubquestion(
            question="How widely are AI agents adopted by data engineering teams?",
            search_queries=["data engineering AI agents survey 2025"],
            evidence_needed="Survey data",
        ),
        PlannedSubquestion(
            question="What risks limit agent adoption in data pipelines?",
            search_queries=["agentic data pipelines risks"],
            evidence_needed="Independent analysis",
        ),
    ]
    return PlanOutput(
        objective="Assess how agentic AI is changing data engineering.",
        subquestions=subqs[:n],
        search_strategy="Prefer official docs and surveys.",
        methodology="Search, extract, compare.",
        scope="Data engineering practice 2024-2025.",
        limitations=["Fast-moving field"],
    )


def make_evidence() -> EvidenceOutput:
    return EvidenceOutput(
        claims=[
            ClaimOutput(
                claim_text="LangGraph checkpointers save graph state at every super-step.",
                subquestion_id="Q1",
                source_ids=["S1"],
                supporting_quotes=["the checkpointer saves a checkpoint of the graph state at every super-step"],
                contradicting=[],
                assessment="established",
                limitations="",
            ),
            ClaimOutput(
                claim_text="62 percent of surveyed data teams were piloting AI agents in 2025.",
                subquestion_id="Q2",
                source_ids=["S2"],
                supporting_quotes=["62 percent reported piloting AI agents for pipeline maintenance"],
                contradicting=[],
                assessment="reported",
                limitations="Single survey.",
            ),
            ClaimOutput(
                claim_text="Vendor claims of 40 percent maintenance reduction lack independent evidence.",
                subquestion_id="Q2",
                source_ids=["S3", "S99"],
                supporting_quotes=["this quote is not anywhere in the source text at all"],
                contradicting=[],
                assessment="contested",
                limitations="",
            ),
            ClaimOutput(
                claim_text="This claim cites only an unknown source.",
                subquestion_id="Q1",
                source_ids=["S42"],
                supporting_quotes=[],
                contradicting=[],
                assessment="reported",
                limitations="",
            ),
        ],
        conflicts=["Vendor figures [S3] are not independently confirmed."],
        gaps=[],
    )


GOOD_BODY = """## Key findings

- LangGraph checkpointers save a checkpoint of the graph state at every super-step [S1].
- In a 2025 survey of 400 data engineering teams, 62 percent reported piloting AI agents [S2].
- Vendors claim agentic tools reduce pipeline maintenance time, but independent evidence is limited [S3].

## Detailed analysis

### How does LangGraph support stateful agent workflows?

LangGraph has a built-in persistence layer implemented through checkpointers [S1].

### How widely are AI agents adopted?

Only 18 percent of surveyed teams had deployed agents in production [S2].

## Competing evidence and viewpoints

Vendor claims of up to 40 percent reductions are not independently confirmed [S3].

## Limitations and uncertainty

Evidence comes from a single survey and vendor statements.

## Conclusion

Agentic tooling is being piloted widely but production adoption remains limited [S2].
"""

BAD_BODY = GOOD_BODY.replace(
    "Only 18 percent of surveyed teams had deployed agents in production [S2].",
    "Only 18 percent of surveyed teams had deployed agents in production [S2]. "
    "Agents cut cloud costs by 75 percent at most enterprises [S9]. "
    "Industry analysts reported that 90 percent of pipelines will be autonomous by 2027.",
)


def make_draft(body: str = GOOD_BODY) -> DraftOutput:
    return DraftOutput(
        title="Agentic AI in Data Engineering",
        executive_summary="AI agents are widely piloted by data teams [S2] while production use is limited [S2].",
        body_markdown=body,
    )


def critic_ok() -> CriticOutput:
    return CriticOutput(
        overall_assessment="Claims are supported by the cited sources.",
        issues=[],
        missing_subquestions=[],
        requires_revision=False,
        requires_more_research=False,
        follow_up_queries=[],
    )


def critic_needs_research() -> CriticOutput:
    return CriticOutput(
        overall_assessment="Adoption risks are not covered.",
        issues=[
            CriticIssueOutput(
                type="missing_coverage", severity="medium", claim_text="", source_ids=[],
                description="Risks are not discussed.", recommendation="Research adoption risks.",
            )
        ],
        missing_subquestions=["Q2"],
        requires_revision=True,
        requires_more_research=True,
        follow_up_queries=["data pipeline agent governance risks"],
    )


def default_llm(**overrides: list[Responder]) -> ScriptedLLM:
    responses: dict[type[BaseModel], list[Responder]] = {
        PlanOutput: [make_plan()],
        EvidenceOutput: [make_evidence()],
        DraftOutput: [make_draft()],
        CriticOutput: [critic_ok()],
    }
    mapping = {"plan": PlanOutput, "evidence": EvidenceOutput, "draft": DraftOutput, "critic": CriticOutput}
    for key, value in overrides.items():
        responses[mapping[key]] = value
    return ScriptedLLM(responses)
