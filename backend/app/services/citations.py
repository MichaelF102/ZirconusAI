"""Deterministic citation and evidence checks.

These checks are intentionally simple and transparent. They do not prove a claim is true; they
catch mechanical failures (citing sources that don't exist, numbers that appear in no cited
source, factual-looking sentences with no citation, quotes that are not in the source) so the
critic does not have to rely on an LLM's judgement alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas.evidence import CriticIssue, SourceRecord

CITATION_RE = re.compile(r"\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]")
_ID_RE = re.compile(r"S\d+")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-']*")
_NUMBER_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(\s?%|\s?percent)?")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")

_STOPWORDS = frozenset(
    """a about above after again against all also am an and any are as at be because been before being
    below between both but by can could did do does doing down during each few for from further had has
    have having he her here hers him his how i if in into is it its itself just may me might more most
    must my no nor not now of off on once only or other our ours out over own same she should so some
    such than that the their theirs them then there these they this those through to too under until up
    very was we were what when where which while who whom why will with would you your yours however
    therefore thus although though whereas including include includes according across within without
    many much several often usually generally particularly especially significant significantly
    new use used using based""".split()
)

_FACTUAL_MARKERS = re.compile(
    r"\b(according to|reported|reports|found|finds|shows|showed|demonstrat\w*|announced|estimated|"
    r"estimates|survey\w*|study|studies|research(?:ers)? (?:show|found)|increase[sd]?|decrease[sd]?|"
    r"grew|declined|percent|million|billion|trillion|majority|doubled|tripled|launched|released|"
    r"according)\b",
    re.IGNORECASE,
)

# Report sections where claims are expected to be cited.
_EXEMPT_SECTIONS = ("limitation", "uncertaint", "methodolog", "research question", "conclusion", "references")


@dataclass
class Sentence:
    text: str
    section: str
    citations: list[str] = field(default_factory=list)

    @property
    def bare_text(self) -> str:
        return re.sub(r"\s+([.,;:!?])", r"\1", CITATION_RE.sub("", self.text)).strip()


def parse_citation_ids(text: str) -> list[str]:
    """All cited source IDs in order of appearance (with repeats)."""
    ids: list[str] = []
    for match in CITATION_RE.finditer(text):
        ids.extend(_ID_RE.findall(match.group(1)))
    return ids


def strip_invalid_citations(markdown: str, valid_ids: set[str]) -> tuple[str, list[str]]:
    """Remove citation IDs that do not resolve to a retrieved source. Returns (markdown, removed_ids)."""
    removed: list[str] = []

    def _replace(match: re.Match) -> str:
        ids = _ID_RE.findall(match.group(1))
        keep = [i for i in ids if i in valid_ids]
        removed.extend(i for i in ids if i not in valid_ids)
        return f"[{', '.join(keep)}]" if keep else ""

    cleaned = CITATION_RE.sub(_replace, markdown)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    return cleaned, removed


def split_sentences(markdown: str) -> list[Sentence]:
    """Split Markdown prose into sentences, tracking the current section heading."""
    sentences: list[Sentence] = []
    section = ""
    in_code = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line:
            continue
        if line.startswith("#"):
            section = line.lstrip("#").strip()
            continue
        if line.startswith("|") and line.endswith("|"):
            if set(line) <= set("|-: "):
                continue
            line = " ".join(cell.strip() for cell in line.strip("|").split("|"))
        line = re.sub(r"^([-*+]|\d+[.)])\s+", "", line)
        line = re.sub(r"[*_`]{1,3}", "", line)
        for part in _SENTENCE_SPLIT_RE.split(line):
            part = part.strip()
            if len(part) < 3:
                continue
            sentences.append(Sentence(text=part, section=section, citations=parse_citation_ids(part)))
    return sentences


def _stem(word: str) -> str:
    """Very light suffix stripping so 'reductions'/'reduction' or 'piloted'/'piloting' match."""
    for suffix, replacement in (("ies", "y"), ("ing", ""), ("ions", "ion"), ("ed", ""), ("es", ""), ("s", ""), ("ly", "")):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)] + replacement
    return word


def content_words(text: str) -> set[str]:
    words = _WORD_RE.findall(CITATION_RE.sub(" ", text.lower()))
    return {_stem(w) for w in words if w not in _STOPWORDS and len(w) > 2 and not w.isdigit()}


def numbers_in(text: str) -> set[str]:
    found = set()
    for value, _pct in _NUMBER_RE.findall(CITATION_RE.sub(" ", text)):
        normalized = value.replace(",", "")
        # Single digits and plausible list ordinals are too noisy to check.
        if len(normalized.replace(".", "")) < 2:
            continue
        found.add(normalized)
    return found


def looks_factual(sentence: str) -> bool:
    bare = CITATION_RE.sub("", sentence)
    if len(bare.split()) < 6:
        return False
    return bool(numbers_in(bare)) or bool(_FACTUAL_MARKERS.search(bare))


def support_score(claim: str, evidence: str) -> float:
    """Fraction of the claim's content words that appear in the evidence text (0–1)."""
    claim_words = content_words(claim)
    if not claim_words:
        return 1.0
    evidence_words = content_words(evidence)
    return len(claim_words & evidence_words) / len(claim_words)


def _normalize(text: str) -> str:
    return " ".join(_WORD_RE.findall(text.lower()))


def quote_in_source(quote: str, source_text: str, threshold: float = 0.85) -> bool:
    """True if the quote appears (near-)verbatim in the source text."""
    q = _normalize(quote)
    if not q:
        return False
    s = _normalize(source_text)
    if q in s:
        return True
    q_words = q.split()
    if len(q_words) < 4:
        return False
    s_words = set(s.split())
    return sum(1 for w in q_words if w in s_words) / len(q_words) >= threshold


@dataclass
class CitationCheck:
    citation_count: int
    valid_citation_count: int
    invalid_ids: list[str]
    cited_ids: list[str]
    uncited_factual: list[str]
    issues: list[CriticIssue]


def check_report_citations(
    markdown: str,
    sources: list[SourceRecord],
    weak_support_threshold: float = 0.25,
    very_weak_threshold: float = 0.1,
) -> CitationCheck:
    """Run all deterministic checks on a draft report body."""
    by_id = {s.source_id: s for s in sources}
    all_ids = parse_citation_ids(markdown)
    invalid = sorted({i for i in all_ids if i not in by_id}, key=lambda x: int(x[1:]))
    cited = sorted({i for i in all_ids if i in by_id}, key=lambda x: int(x[1:]))
    issues: list[CriticIssue] = []
    uncited: list[str] = []

    if invalid:
        issues.append(
            CriticIssue(
                type="invalid_citation",
                severity="high",
                description=f"Citations reference sources that were never retrieved: {', '.join(invalid)}",
                source_ids=invalid,
                recommendation="Cite only source IDs from the provided source list.",
                origin="deterministic",
            )
        )

    for sentence in split_sentences(markdown):
        section = sentence.section.lower()
        exempt = any(marker in section for marker in _EXEMPT_SECTIONS)
        valid_cites = [c for c in sentence.citations if c in by_id]
        if not valid_cites:
            if not exempt and looks_factual(sentence.text):
                uncited.append(sentence.bare_text)
                issues.append(
                    CriticIssue(
                        type="unsupported_claim",
                        severity="medium",
                        description="Factual statement has no citation.",
                        claim_text=sentence.bare_text,
                        recommendation="Add a citation to a supporting source, qualify it, or remove it.",
                        origin="deterministic",
                    )
                )
            continue

        evidence = "\n".join(by_id[c].evidence_text for c in valid_cites)
        missing_numbers = sorted(numbers_in(sentence.text) - numbers_in(evidence))
        if missing_numbers:
            only_years = all(re.fullmatch(r"(19|20)\d{2}", n) for n in missing_numbers)
            issues.append(
                CriticIssue(
                    type="unsupported_claim",
                    severity="medium" if only_years else "high",
                    description=(
                        f"Figures {', '.join(missing_numbers)} do not appear in the cited source text "
                        f"({', '.join(valid_cites)})."
                    ),
                    claim_text=sentence.bare_text,
                    source_ids=valid_cites,
                    recommendation="Use the figure stated in the source, cite the source that contains it, or remove it.",
                    origin="deterministic",
                )
            )
            continue

        score = support_score(sentence.text, evidence)
        if score < weak_support_threshold and len(content_words(sentence.text)) >= 4:
            # Lexical overlap is a weak signal (paraphrase is legitimate), so only near-zero overlap
            # against full-text sources is material. Semantic support is judged by the LLM critic.
            snippet_only = all(by_id[c].extraction_status != "extracted" for c in valid_cites)
            issues.append(
                CriticIssue(
                    type="weak_support",
                    severity="medium" if score < very_weak_threshold and not snippet_only else "low",
                    description=(
                        f"Little lexical overlap ({score:.0%}) between the claim and cited source text"
                        + (" (sources are snippet-only)" if snippet_only else "")
                        + "."
                    ),
                    claim_text=sentence.bare_text,
                    source_ids=valid_cites,
                    recommendation="Verify the citation supports this statement or rephrase closer to the source.",
                    origin="deterministic",
                )
            )

    return CitationCheck(
        citation_count=len(all_ids),
        valid_citation_count=sum(1 for i in all_ids if i in by_id),
        invalid_ids=invalid,
        cited_ids=cited,
        uncited_factual=uncited,
        issues=issues,
    )
