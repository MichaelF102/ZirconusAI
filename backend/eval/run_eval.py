"""Evaluation runner.

Two modes:

  critic    Measure critic precision/recall on hand-labeled sentences (eval/critic_cases.json).
            Deterministic checks run offline; add --llm to also run the Gemini critic.
  research  Run the real research workflow on questions from eval/questions.json and record
            citation validity, coverage, source diversity, latency and API usage. Also exports a
            CSV of sampled cited sentences for *manual* claim-support review.

Results are written to eval/results/. Nothing here fabricates numbers: every metric is computed
from an actual run, and claim support must be labelled by a human reviewer.

Usage (from backend/):
    python -m eval.run_eval critic [--llm]
    python -m eval.run_eval research [--limit 3] [--ids tech-01,biz-01] [--depth quick]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.graph.context import RunContext
from app.graph.workflow import build_workflow
from app.schemas.evidence import SourceRecord
from app.schemas.research import ResearchRequest
from app.services.citations import check_report_citations, parse_citation_ids, split_sentences
from app.services.research_service import default_dependencies

HERE = Path(__file__).parent
RESULTS = HERE / "results"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _prf(tp: int, fp: int, fn: int, tn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall, "f1": f1}


# ---------------------------------------------------------------------------
# Critic evaluation
# ---------------------------------------------------------------------------
def _case_sources(data: dict) -> list[SourceRecord]:
    now = datetime.now(timezone.utc)
    return [
        SourceRecord(source_id=sid, title=sid, url=f"https://eval.invalid/{sid}", domain="eval.invalid",
                     retrieved_at=now, extracted_content=text, extraction_status="extracted")
        for sid, text in data["sources"].items()
    ]


async def _llm_flags(data: dict, sources: list[SourceRecord]) -> set[str]:
    """Ask the real LLM critic to review a draft built from all case sentences."""
    from app.graph.llm_schemas import CriticOutput
    from app.graph.prompts import CRITIC_SYSTEM, critic_prompt
    from app.schemas.evidence import EvidenceMatrix
    from app.schemas.research import ResearchPlan, SubQuestion

    settings = get_settings()
    llm, search, extractor = default_dependencies(settings)
    ctx = RunContext(settings=settings, llm=llm, search=search, extractor=extractor)
    draft = "## Key findings\n\n" + "\n".join(f"- {c['sentence']}" for c in data["cases"])
    plan = ResearchPlan(objective="Evaluate critic", subquestions=[SubQuestion(id="Q1", question="Evaluate critic")])
    out = await ctx.structured(
        CriticOutput, CRITIC_SYSTEM, critic_prompt("Critic evaluation", plan, EvidenceMatrix(), sources, draft, []),
        label="critic-eval",
    )
    flagged = set()
    for issue in out.issues:
        if issue.severity == "low":
            continue
        for case in data["cases"]:
            # Match by substantial overlap with the quoted sentence.
            bare = case["sentence"].split(" [")[0].rstrip(".").lower()
            if bare[:40] in issue.claim_text.lower() or issue.claim_text.lower()[:40] in bare:
                flagged.add(case["id"])
    return flagged


def run_critic_eval(use_llm: bool) -> dict:
    data = json.loads((HERE / "critic_cases.json").read_text())
    sources = _case_sources(data)
    det_flags: dict[str, bool] = {}
    per_case = []
    for case in data["cases"]:
        check = check_report_citations(f"## Key findings\n\n{case['sentence']}", sources)
        flagged = any(i.severity in ("medium", "high") for i in check.issues)
        det_flags[case["id"]] = flagged
        per_case.append({"id": case["id"], "label": case["label"], "deterministic_flag": flagged,
                         "issues": [f"{i.severity}:{i.type}" for i in check.issues]})

    llm_flags: set[str] = set()
    if use_llm:
        llm_flags = asyncio.run(_llm_flags(data, sources))
        for row in per_case:
            row["llm_flag"] = row["id"] in llm_flags
            row["combined_flag"] = row["deterministic_flag"] or row["llm_flag"]

    def score(key: str) -> dict:
        tp = sum(1 for r in per_case if r[key] and r["label"] == "unsupported")
        fp = sum(1 for r in per_case if r[key] and r["label"] == "supported")
        fn = sum(1 for r in per_case if not r[key] and r["label"] == "unsupported")
        tn = sum(1 for r in per_case if not r[key] and r["label"] == "supported")
        return _prf(tp, fp, fn, tn)

    result = {"mode": "critic", "timestamp": _stamp(), "cases": len(per_case),
              "deterministic": score("deterministic_flag"), "per_case": per_case}
    if use_llm:
        result["llm"] = score("llm_flag")
        result["combined"] = score("combined_flag")
    return result


# ---------------------------------------------------------------------------
# Research evaluation
# ---------------------------------------------------------------------------
async def _run_question(item: dict, depth: str) -> tuple[dict, list[dict]]:
    settings = get_settings()
    llm, search, extractor = default_dependencies(settings)
    ctx = RunContext(settings=settings, llm=llm, search=search, extractor=extractor)
    graph = build_workflow()
    request = ResearchRequest(question=item["question"], depth=depth)
    config = {"configurable": {"thread_id": item["id"], "ctx": ctx}, "recursion_limit": 50}
    started = time.perf_counter()
    row = {"id": item["id"], "category": item["category"], "question": item["question"]}
    review_rows: list[dict] = []
    try:
        final = await asyncio.wait_for(
            graph.ainvoke({"research_id": item["id"], "request": request, "warnings": []}, config),
            timeout=settings.max_research_seconds,
        )
    except Exception as exc:
        row.update(completed=False, error=f"{type(exc).__name__}: {exc}"[:300])
        final = None
    row["latency_seconds"] = round(time.perf_counter() - started, 1)
    row.update(ctx.usage.model_dump())
    if final is None:
        return row, review_rows

    report = final["report"]
    q = report.quality_assessment
    body_ids = parse_citation_ids(report.report_markdown.split("## References")[0])
    counts = Counter(body_ids)
    check = check_report_citations(report.report_markdown.split("## References")[0], report.sources)
    coverage = q.subquestion_coverage
    row.update(
        completed=True,
        status=report.status.value,
        quality_status=q.status,
        citation_validity=round(q.citation_validity, 3),
        citations=q.citation_count,
        sources_retrieved=len(report.sources),
        sources_extracted=sum(1 for s in report.sources if s.extraction_status == "extracted"),
        cited_sources=q.cited_source_count,
        distinct_cited_domains=q.distinct_cited_domains,
        top_source_citation_share=round(counts.most_common(1)[0][1] / len(body_ids), 3) if body_ids else None,
        subquestion_coverage=round(sum(coverage.values()) / len(coverage), 3) if coverage else None,
        revision_cycles=q.revision_cycles,
        unresolved_issues=len(q.unresolved_issues),
        uncited_factual_sentences=check.uncited_factual.__len__(),
        critic_issues_final_pass=len(report.critic.issues) if report.critic else 0,
    )

    by_id = {s.source_id: s for s in report.sources}
    cited_sentences = [s for s in split_sentences(report.report_markdown.split("## References")[0]) if s.citations]
    for sentence in random.Random(item["id"]).sample(cited_sentences, min(5, len(cited_sentences))):
        sid = next((c for c in sentence.citations if c in by_id), None)
        if sid is None:
            continue
        review_rows.append({
            "question_id": item["id"], "sentence": sentence.bare_text, "source_id": sid,
            "source_url": by_id[sid].url, "source_excerpt": by_id[sid].evidence_text[:1500],
            "human_label (supported/partial/unsupported)": "",
        })
    return row, review_rows


def run_research_eval(limit: int | None, ids: list[str] | None, depth: str) -> tuple[dict, list[dict]]:
    questions = json.loads((HERE / "questions.json").read_text())
    if ids:
        questions = [q for q in questions if q["id"] in ids]
    if limit:
        questions = questions[:limit]
    rows, review = [], []
    for item in questions:
        print(f"→ {item['id']}: {item['question']}", flush=True)
        row, sampled = asyncio.run(_run_question(item, depth))
        print(f"   {json.dumps({k: row.get(k) for k in ('completed', 'quality_status', 'citation_validity', 'latency_seconds', 'llm_calls', 'search_calls')})}")
        rows.append(row)
        review.extend(sampled)

    done = [r for r in rows if r.get("completed")]

    def mean(key: str):
        vals = [r[key] for r in done if r.get(key) is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    summary = {
        "questions": len(rows),
        "completion_rate": round(len(done) / len(rows), 3) if rows else None,
        "mean_citation_validity": mean("citation_validity"),
        "mean_subquestion_coverage": mean("subquestion_coverage"),
        "mean_distinct_cited_domains": mean("distinct_cited_domains"),
        "mean_top_source_citation_share": mean("top_source_citation_share"),
        "mean_latency_seconds": mean("latency_seconds"),
        "mean_llm_calls": mean("llm_calls"),
        "mean_input_tokens": mean("input_tokens"),
        "mean_output_tokens": mean("output_tokens"),
        "mean_search_calls": mean("search_calls"),
        "claim_support": "Label eval/results/*claims_for_review.csv manually to compute claim support.",
    }
    return {"mode": "research", "timestamp": _stamp(), "depth": depth, "summary": summary, "runs": rows}, review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("critic")
    c.add_argument("--llm", action="store_true", help="also evaluate the Gemini critic (uses API quota)")
    r = sub.add_parser("research")
    r.add_argument("--limit", type=int)
    r.add_argument("--ids", type=lambda s: s.split(","))
    r.add_argument("--depth", default="quick", choices=["quick", "standard", "deep"])
    args = parser.parse_args()

    RESULTS.mkdir(exist_ok=True)
    stamp = _stamp()
    if args.mode == "critic":
        result = run_critic_eval(args.llm)
        path = RESULTS / f"{stamp}_critic.json"
        path.write_text(json.dumps(result, indent=2))
        print(json.dumps({k: v for k, v in result.items() if k != "per_case"}, indent=2))
    else:
        result, review = run_research_eval(args.limit, args.ids, args.depth)
        path = RESULTS / f"{stamp}_research.json"
        path.write_text(json.dumps(result, indent=2, default=str))
        if result["runs"]:
            with open(RESULTS / f"{stamp}_research.csv", "w", newline="") as fh:
                keys = sorted({k for row in result["runs"] for k in row})
                writer = csv.DictWriter(fh, fieldnames=keys)
                writer.writeheader()
                writer.writerows(result["runs"])
        if review:
            with open(RESULTS / f"{stamp}_claims_for_review.csv", "w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(review[0]))
                writer.writeheader()
                writer.writerows(review)
        print(json.dumps(result["summary"], indent=2))
    print(f"Saved results to {path}")


if __name__ == "__main__":
    main()
