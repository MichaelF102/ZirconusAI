from datetime import datetime, timezone

from app.schemas.evidence import SourceRecord
from app.services.citations import (
    check_report_citations,
    looks_factual,
    parse_citation_ids,
    quote_in_source,
    split_sentences,
    strip_invalid_citations,
    support_score,
)


def _src(sid: str, text: str, status: str = "extracted") -> SourceRecord:
    return SourceRecord(
        source_id=sid, title=f"Source {sid}", url=f"https://example.com/{sid}", domain="example.com",
        retrieved_at=datetime.now(timezone.utc), extracted_content=text if status == "extracted" else "",
        snippet=text if status != "extracted" else "", extraction_status=status,
    )


SOURCES = [
    _src("S1", "LangGraph checkpointers save a snapshot of graph state at every super-step for persistence."),
    _src("S2", "The 2025 survey found 62 percent of 400 data teams were piloting AI agents."),
]


def test_parse_citation_ids_handles_groups_and_repeats():
    text = "A [S1]. B [S2, S3]. C [S1;S4]. Not a cite [1] or [Source]."
    assert parse_citation_ids(text) == ["S1", "S2", "S3", "S1", "S4"]


def test_invalid_citations_are_stripped_and_reported():
    text = "Valid claim [S1]. Mixed claim [S1, S7]. Invented claim [S9]."
    cleaned, removed = strip_invalid_citations(text, {"S1", "S2"})
    assert cleaned == "Valid claim [S1]. Mixed claim [S1]. Invented claim."
    assert removed == ["S7", "S9"]


def test_check_flags_invalid_citation_as_high_severity():
    result = check_report_citations("## Key findings\n\nCheckpointers save graph state [S1] [S5].", SOURCES)
    assert result.invalid_ids == ["S5"]
    assert any(i.type == "invalid_citation" and i.severity == "high" for i in result.issues)
    assert result.citation_count == 2 and result.valid_citation_count == 1


def test_uncited_factual_sentence_is_flagged_but_limitations_are_exempt():
    md = (
        "## Key findings\n\nAnalysts reported that 90 percent of pipelines will be autonomous by 2027.\n\n"
        "## Limitations and uncertainty\n\nThe survey reported 62 percent adoption among only 400 teams."
    )
    result = check_report_citations(md, SOURCES)
    assert result.uncited_factual == ["Analysts reported that 90 percent of pipelines will be autonomous by 2027."]
    assert any(i.type == "unsupported_claim" and i.origin == "deterministic" for i in result.issues)


def test_numbers_missing_from_cited_source_are_high_severity():
    md = "## Key findings\n\nThe survey found 75 percent of data teams were piloting AI agents [S2]."
    result = check_report_citations(md, SOURCES)
    issue = next(i for i in result.issues if "75" in i.description)
    assert issue.severity == "high" and issue.source_ids == ["S2"]


def test_number_check_matches_whole_numbers_only():
    md = "## Key findings\n\nAgents reduced incidents by 40 percent across respondents [S2]."
    result = check_report_citations(md, SOURCES)  # S2 mentions 400, not 40
    assert any(i.severity == "high" and "40" in i.description for i in result.issues)


def test_supported_claim_passes_cleanly():
    md = "## Key findings\n\nThe 2025 survey found 62 percent of 400 data teams were piloting AI agents [S2]."
    result = check_report_citations(md, SOURCES)
    assert result.issues == []
    assert result.cited_ids == ["S2"]


def test_weak_lexical_support_is_flagged():
    md = "## Detailed analysis\n\nQuantum annealing hardware dramatically accelerates protein folding simulations [S1]."
    result = check_report_citations(md, SOURCES)
    assert any(i.type == "weak_support" and i.severity == "medium" for i in result.issues)


def test_paraphrase_with_partial_overlap_is_not_material():
    md = "## Detailed analysis\n\nPersistence in LangGraph keeps a snapshot of workflow progress after each step [S1]."
    result = check_report_citations(md, SOURCES)
    assert all(i.severity == "low" for i in result.issues)


def test_weak_support_on_snippet_only_source_is_low_severity():
    sources = [_src("S1", "Totally unrelated snippet about gardening tools.", status="snippet_only")]
    md = "## Detailed analysis\n\nQuantum annealing hardware dramatically accelerates protein folding [S1]."
    result = check_report_citations(md, sources)
    assert [i.severity for i in result.issues if i.type == "weak_support"] == ["low"]


def test_split_sentences_tracks_sections_and_lists():
    md = "# Title\n\n## Key findings\n\n- First point [S1]. Second point.\n\n| a | b |\n|---|---|\n| x | y |"
    sentences = split_sentences(md)
    assert sentences[0].section == "Key findings"
    assert sentences[0].citations == ["S1"]
    assert sentences[1].text == "Second point."


def test_quote_verification():
    text = SOURCES[0].extracted_content
    assert quote_in_source("save a snapshot of graph state", text)
    assert quote_in_source("Save a snapshot of the graph state at every super-step", text)
    assert not quote_in_source("LangGraph was released by Google in 1999", text)


def test_support_score_and_factual_heuristics():
    assert support_score("checkpointers save graph state", SOURCES[0].extracted_content) == 1.0
    assert support_score("bananas grow quickly", SOURCES[0].extracted_content) == 0.0
    assert looks_factual("The survey found that most teams use agents in production today.")
    assert not looks_factual("This section discusses the topic.")
