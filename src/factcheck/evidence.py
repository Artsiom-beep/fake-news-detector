from __future__ import annotations

import re
from datetime import datetime
from typing import List

try:
    from ..nli import classify_claim_vs_evidence
except ImportError:
    from nli import classify_claim_vs_evidence

from .config import PipelineConfig
from .schemas import ClaimCandidate, EvidenceItem, FactCheckTrace, RetrievedDocument

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
NEGATION_MARKERS = {
    "not",
    "no",
    "never",
    "without",
    "false",
    "fake",
    "hoax",
    "misleading",
    "incorrect",
    "ineffective",
    "unsupported",
}


def _token_overlap(a: str, b: str) -> float:
    left = set(re.findall(r"\w+", (a or "").lower()))
    right = set(re.findall(r"\w+", (b or "").lower()))
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), 1)


def _split_passages(text: str) -> List[str]:
    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT.split(text or "") if len(sentence.strip()) >= 25]
    if not sentences:
        return []
    passages: List[str] = []
    for index in range(len(sentences)):
        window = sentences[index : index + 2]
        if window:
            passages.append(" ".join(window))
    return passages[:12]


def _map_explicit_verdict(verdict: str) -> str:
    low = (verdict or "").lower().strip()
    if low == "support":
        return "support"
    if low == "refute":
        return "refute"
    if low == "uncertain":
        return "neutral"
    return ""


def _map_nli_label(label: str) -> str:
    low = (label or "").lower().strip()
    if low == "supported":
        return "support"
    if low == "refuted":
        return "refute"
    return "neutral"


def _invert_stance(stance: str) -> str:
    if stance == "support":
        return "refute"
    if stance == "refute":
        return "support"
    return "neutral"


def _has_negation_marker(text: str) -> bool:
    tokens = set(re.findall(r"\w+", (text or "").lower()))
    lowered = (text or "").lower()
    return bool(tokens & NEGATION_MARKERS) or any(
        phrase in lowered
        for phrase in ("did not", "does not", "do not", "is not", "are not", "was not", "were not")
    )


def _resolve_explicit_stance(
    claim: ClaimCandidate,
    document: RetrievedDocument,
    explicit_stance: str,
    use_nli: bool = True,
) -> tuple[str, float]:
    relation_text = document.claim_text or document.title
    alignment_overlap = max(document.claim_match_score, _token_overlap(claim.normalized_text, relation_text))
    if not relation_text:
        return explicit_stance, max(document.claim_match_score, 0.45)
    if alignment_overlap < 0.28:
        return "neutral", alignment_overlap

    if not use_nli:
        if alignment_overlap >= 0.45 and (_has_negation_marker(claim.normalized_text) ^ _has_negation_marker(relation_text)):
            return _invert_stance(explicit_stance), alignment_overlap
        if alignment_overlap >= 0.52:
            return explicit_stance, alignment_overlap
        return "neutral", alignment_overlap

    relation = classify_claim_vs_evidence(claim.normalized_text, relation_text[:600])
    relation_stance = _map_nli_label(relation.get("label", "neutral"))
    relation_score = float(relation.get("score", 0.0))

    if relation_stance == "support":
        return explicit_stance, max(alignment_overlap, relation_score)
    if relation_stance == "refute":
        return _invert_stance(explicit_stance), max(alignment_overlap, relation_score)
    if alignment_overlap >= 0.72:
        return explicit_stance, alignment_overlap
    return "neutral", max(alignment_overlap, 0.35)


def _freshness_score(claim: ClaimCandidate, document: RetrievedDocument) -> float:
    current_year = datetime.utcnow().year
    doc_text = f"{document.title} {document.snippet} {document.content[:500]}"
    doc_years = re.findall(r"\b(?:19|20)\d{2}\b", doc_text)
    if claim.dates and any(year in doc_text for year in claim.dates):
        return 0.95
    if doc_years:
        newest = max(int(year) for year in doc_years)
        age = current_year - newest
        if age <= 1:
            return 0.9
        if age <= 3:
            return 0.7
        return 0.45
    return 0.55


def _relevance_score(claim: ClaimCandidate, document: RetrievedDocument, passage: str) -> float:
    lexical = _token_overlap(claim.normalized_text, passage)
    title_overlap = _token_overlap(claim.normalized_text, document.title)
    entity_bonus = 0.2 if any(entity.lower() in passage.lower() for entity in claim.entities[:2]) else 0.0
    date_bonus = 0.15 if any(date.lower() in passage.lower() for date in claim.dates[:1]) else 0.0
    raw = (0.55 * lexical) + (0.25 * title_overlap) + entity_bonus + date_bonus
    return min(1.0, raw)


def score_evidence_for_claim(
    claim: ClaimCandidate,
    documents: List[RetrievedDocument],
    trace: FactCheckTrace,
    config: PipelineConfig,
) -> List[EvidenceItem]:
    evidence_items: List[EvidenceItem] = []
    seen_domains = set()

    for document in documents:
        if config.mode == "factcheck_only" and not document.explicit_verdict:
            continue
        if document.is_factcheck_article and document.ruling_text:
            passages = [document.ruling_text]
        else:
            passages = _split_passages(document.content) or [document.snippet or document.content[:300]]
        best_item: EvidenceItem | None = None

        for passage in passages:
            relevance = _relevance_score(claim, document, passage)
            if relevance < 0.12:
                continue
            explicit_stance = _map_explicit_verdict(document.explicit_verdict)
            stance_method = "explicit_verdict" if explicit_stance else ""
            if explicit_stance:
                stance, alignment_score = _resolve_explicit_stance(
                    claim,
                    document,
                    explicit_stance,
                    use_nli=config.mode != "factcheck_only",
                )
                if config.mode == "factcheck_only" and stance == "neutral":
                    continue
                if stance == "neutral":
                    stance_strength = min(0.72, 0.34 + 0.22 * max(alignment_score, relevance))
                else:
                    stance_strength = min(
                        0.96,
                        0.68
                        + 0.14 * max(document.claim_match_score, relevance)
                        + 0.10 * document.source_trust
                        + 0.08 * alignment_score,
                    )
            else:
                nli = classify_claim_vs_evidence(claim.normalized_text, passage[:1400])
                stance = _map_nli_label(nli.get("label", "neutral"))
                stance_strength = float(nli.get("score", 0.0))
                stance_method = str(nli.get("method", "nli") or "nli")
                if (
                    stance != "neutral"
                    and not document.is_factcheck_article
                    and document.source_type in {"primary_news", "major_news", "unknown"}
                    and document.title
                ):
                    meaningful_numbers = [number for number in claim.numbers if number not in {"19"}]
                    has_structured_cues = bool(claim.entities or claim.dates or meaningful_numbers)
                    title_nli = classify_claim_vs_evidence(claim.normalized_text, document.title[:320])
                    title_stance = _map_nli_label(title_nli.get("label", "neutral"))
                    title_coverage = _token_overlap(claim.normalized_text, document.title)
                    if not has_structured_cues and title_coverage < 0.75:
                        title_stance = "neutral"
                    if title_stance == "neutral" and document.claim_match_score < 0.78:
                        stance = "neutral"
                        stance_strength = min(0.7, max(0.42, stance_strength * 0.6))
                        stance_method = f"{stance_method}+title_guard"

            freshness = _freshness_score(claim, document)
            independence_bonus = 1.0 if document.domain not in seen_domains else 0.4
            explicit_bonus = 0.12 if explicit_stance else 0.0
            factcheck_bonus = 0.08 if document.is_factcheck_article else 0.0
            final_score = (
                0.35 * relevance
                + 0.25 * stance_strength
                + 0.20 * document.source_trust
                + 0.10 * freshness
                + 0.10 * independence_bonus
                + explicit_bonus
                + factcheck_bonus
            )
            candidate = EvidenceItem(
                url=document.url,
                title=document.title,
                stance=stance,
                score=final_score,
                snippet=document.snippet[:280],
                passage=passage[:420],
                source_type=document.source_type,
                source_trust=document.source_trust,
                relevance=relevance,
                freshness=freshness,
                domain=document.domain,
                is_factcheck_article=document.is_factcheck_article,
                explicit_verdict=document.explicit_verdict,
                verdict_source=document.verdict_source,
                claim_match_score=document.claim_match_score,
                stance_confidence=stance_strength,
                stance_method=stance_method,
            )
            if best_item is None or candidate.score > best_item.score:
                best_item = candidate

        if best_item is None:
            continue

        evidence_items.append(best_item)
        seen_domains.add(document.domain)

    ranked = sorted(
        evidence_items,
        key=lambda item: (item.score, item.source_trust, item.relevance),
        reverse=True,
    )

    diverse_ranked: List[EvidenceItem] = []
    seen_domains = set()
    for item in ranked:
        domain_key = item.domain or item.url
        if domain_key in seen_domains:
            continue
        seen_domains.add(domain_key)
        diverse_ranked.append(item)
        if len(diverse_ranked) >= config.max_evidence:
            break

    trace.selected_passages.extend(
        [
            {
                "url": item.url,
                "title": item.title,
                "stance": item.stance,
                "score": round(item.score, 4),
                "stance_confidence": round(item.stance_confidence, 4),
                "stance_method": item.stance_method,
                "passage": item.passage,
            }
            for item in diverse_ranked
        ]
    )
    return diverse_ranked
