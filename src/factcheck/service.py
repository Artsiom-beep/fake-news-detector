from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import replace
from typing import List

from .cache import get_cache
from .claims import extract_claims, is_low_specificity_meta_claim
from .common_knowledge import COMMON_FACTS, decide_common_knowledge
from .config import FACTCHECK_ONLY_DOMAINS, RESEARCH_DOMAINS, PipelineConfig, build_config
from .decision import decide_claim, finalize_result
from .evidence import score_evidence_for_claim
from .ingest import canonicalize_text, fetch_url_text, is_likely_article_url
from .news_credibility import analyze_news_credibility, is_news_source_url
from .retrieval import retrieve_documents
from .schemas import ClaimCandidate, ClaimDecision, FactCheckResult, FactCheckTrace, RetrievedDocument
from .source_registry import classify_source

LOGGER = logging.getLogger("factcheck")


def _log_result(result: FactCheckResult) -> None:
    if not LOGGER.handlers:
        return
    LOGGER.info(json.dumps(result.to_public_dict(), ensure_ascii=False))


def _looks_like_simple_knowledge_text(text: str) -> bool:
    clean = canonicalize_text(text)
    clean = re.sub(r"\b(?:[A-Za-z]\.){2,}", lambda match: match.group(0).replace(".", ""), clean)
    if not clean or len(clean) > 120:
        return False
    low = re.sub(r"[.!?]+$", "", clean.lower()).strip()
    numeric_words = r"(greater|less|lower|higher|more|fewer|equal|equals|plus|minus|times|multiplied|divided|above|below|under|over|at least|at most)"
    if re.search(r"\d", low) and (re.search(r"[<>]=?|=", low) or re.search(rf"\b{numeric_words}\b", low)):
        return True
    number_word = (
        r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
        r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
        r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
    )
    if re.search(rf"\b(?:{number_word})\b", low) and re.search(rf"\b{numeric_words}\b", low):
        return True
    if re.search(r"\b(causes?|cures?|includes?|orbits?|prevents?|treats?)\b", low):
        return True
    if not re.search(r"\b(is|are|was|were)\b", low):
        return False
    if re.match(
        r"^[a-z0-9][a-z0-9\s'.-]{1,80}\s+"
        r"(?:is|are)\s+(?:not\s+)?(?:the\s+)?"
        r"(?:(?:u\s*s|us|american)\s+)?president(?:\s+of\s+(?:the\s+)?united\s+states)?$",
        low,
    ):
        return True
    if re.match(
        r"^[a-z0-9][a-z0-9\s'.-]{1,80}\s+"
        r"(?:is|are)\s+(?:not\s+)?(?:the\s+)?"
        r"(?:uk\s+|british\s+)?prime\s+minister(?:\s+of\s+(?:the\s+)?united\s+kingdom)?$",
        low,
    ):
        return True
    if re.match(
        r"^[a-z0-9][a-z0-9\s'.-]{1,80}\s+"
        r"(?:is|are)\s+(?:not\s+)?(?:the\s+)?"
        r"(?:(?:chair|chairman)\s+of\s+(?:the\s+)?federal\s+reserve|federal\s+reserve\s+chair|fed\s+chair)$",
        low,
    ):
        return True

    simple_subjects = set(COMMON_FACTS)
    if any(re.search(rf"\b{re.escape(subject)}\b", low) for subject in simple_subjects):
        return True

    current_event_markers = {
        "announced",
        "arrested",
        "campaign",
        "court",
        "election",
        "government",
        "killed",
        "minister",
        "police",
        "president",
        "reported",
        "said",
        "stock",
        "today",
        "war",
        "yesterday",
    }
    if any(re.search(rf"\b{re.escape(marker)}\b", low) for marker in current_event_markers):
        return False

    # Short "X is Y" statements are usually stable everyday facts. The
    # common-knowledge layer will still abstain if it cannot find exact support.
    return bool(re.match(r"^[a-z0-9][a-z0-9\s'-]{1,55}\s+(?:is|are|was|were)\s+.{2,60}$", low))


def _factcheck_strategy_config(config: PipelineConfig) -> PipelineConfig:
    return replace(
        config,
        mode="factcheck_only",
        fast_mode=False,
        max_search_results=min(config.max_search_results, 4),
        max_documents=min(config.max_documents, 6),
        max_evidence=min(config.max_evidence, 5),
        targeted_domains=list(FACTCHECK_ONLY_DOMAINS),
    )


def _trusted_research_strategy_config(config: PipelineConfig) -> PipelineConfig:
    return replace(
        config,
        mode="research",
        fast_mode=False,
        max_search_results=config.max_search_results,
        max_documents=config.max_documents,
        max_evidence=config.max_evidence,
        targeted_domains=list(RESEARCH_DOMAINS),
        allow_prior_fallback=False,
    )


def _claim_candidates(article_text: str, config: PipelineConfig) -> list[ClaimCandidate]:
    claims = extract_claims(article_text, max_claims=config.max_claims)
    if claims or not _looks_like_simple_knowledge_text(article_text):
        return claims
    normalized = canonicalize_text(article_text)
    return [
        ClaimCandidate(
            raw_text=normalized,
            normalized_text=normalized,
            score=3.0,
            numbers=re.findall(r"-?\d+(?:\.\d+)?", normalized),
            source="text",
        )
    ]


def _input_factcheck_document(fetched: dict, raw_url: str) -> RetrievedDocument:
    final_url = fetched.get("url", raw_url) or raw_url
    profile = classify_source(final_url)
    return RetrievedDocument(
        query="input_url",
        url=final_url,
        canonical_url=final_url,
        title=fetched.get("title", ""),
        snippet=fetched.get("claim_text", "") or fetched.get("ruling_text", "")[:280],
        content=fetched.get("text", ""),
        source_url=final_url,
        source_type=profile.source_type,
        source_trust=profile.trust,
        domain=profile.domain,
        retrieval_score=1.0,
        fetch_source=fetched.get("fetch_source", "direct"),
        published_at=fetched.get("published_at", ""),
        author=fetched.get("author", ""),
        canonical_article_url=fetched.get("canonical_article_url", final_url),
        is_factcheck_article=bool(fetched.get("is_factcheck_article")),
        explicit_verdict=fetched.get("explicit_verdict", ""),
        explicit_verdict_label=fetched.get("explicit_verdict_label", ""),
        verdict_source=fetched.get("verdict_source", ""),
        claim_text=fetched.get("claim_text", ""),
        ruling_text=fetched.get("ruling_text", ""),
        claim_match_score=1.0 if fetched.get("claim_text") else 0.72,
    )


def _uncertain_result(summary: str, trace: FactCheckTrace, config: PipelineConfig, claim: str = "") -> FactCheckResult:
    return FactCheckResult(
        verdict="uncertain",
        confidence=0.2,
        summary=summary,
        claim=claim,
        evidence=[],
        trace=trace,
        claims=[],
        config=config.snapshot(),
        pipeline_version=config.pipeline_version,
    )


def _run_claim_verdict_path(
    article_text: str,
    config: PipelineConfig,
    trace: FactCheckTrace,
    cache,
    input_factcheck_document: RetrievedDocument | None = None,
) -> FactCheckResult:
    factcheck_config = _factcheck_strategy_config(config)
    research_config = _trusted_research_strategy_config(config)
    start_claims = time.perf_counter()
    claims = _claim_candidates(article_text, config)
    trace.stage_timings_ms["claims"] = (time.perf_counter() - start_claims) * 1000

    decisions: List[ClaimDecision] = []
    simple_knowledge_input = _looks_like_simple_knowledge_text(article_text)

    def score_and_decide(
        claim: ClaimCandidate,
        decision_config: PipelineConfig,
        input_document: RetrievedDocument | None = None,
    ) -> ClaimDecision:
        retrieval_start = time.perf_counter()
        documents = (
            [input_document]
            if input_document is not None
            else retrieve_documents(claim, trace=trace, config=decision_config, cache=cache)
        )
        trace.stage_timings_ms.setdefault("retrieval", 0.0)
        trace.stage_timings_ms["retrieval"] += (time.perf_counter() - retrieval_start) * 1000

        evidence_start = time.perf_counter()
        evidence = score_evidence_for_claim(claim, documents, trace=trace, config=decision_config)
        trace.stage_timings_ms.setdefault("evidence", 0.0)
        trace.stage_timings_ms["evidence"] += (time.perf_counter() - evidence_start) * 1000

        decision_start = time.perf_counter()
        decision = decide_claim(claim, evidence, trace=trace, config=decision_config)
        trace.stage_timings_ms.setdefault("decision", 0.0)
        trace.stage_timings_ms["decision"] += (time.perf_counter() - decision_start) * 1000
        return decision

    def should_try_trusted_research(decision: ClaimDecision) -> bool:
        if input_factcheck_document is not None or decision.verdict != "uncertain":
            return False
        reason_text = " ".join(decision.reasons)
        return any(
            marker in reason_text
            for marker in (
                "no_explicit_factcheck_verdict",
                "blocked_conflicting_explicit_verdicts",
                "hard_verdict_policy=blocked",
            )
        )

    def should_use_trusted_research(decision: ClaimDecision) -> bool:
        return (
            decision.verdict in {"true", "fake"}
            and decision.confidence >= 0.56
            and decision.trusted_hits >= 1
        )

    for claim in claims:
        if simple_knowledge_input:
            knowledge_decision = decide_common_knowledge(claim, trace=trace)
            if knowledge_decision is not None:
                decisions.append(knowledge_decision)
                continue
            trace.fallbacks_used.append("common_knowledge_no_match")

        if is_low_specificity_meta_claim(claim):
            reasons = [
                "strategy=factcheck_verdict",
                "hard_verdict_policy=low_specificity_meta_claim",
            ]
            trace.decision_reasons.extend([f"{claim.normalized_text}: {reason}" for reason in reasons])
            trace.fallbacks_used.append("low_specificity_meta_claim")
            decisions.append(
                ClaimDecision(
                    claim=claim,
                    verdict="uncertain",
                    confidence=0.2,
                    support_score=0.0,
                    refute_score=0.0,
                    neutral_score=0.0,
                    independent_sources=0,
                    trusted_hits=0,
                    reasons=reasons,
                    evidence=[],
                )
            )
            continue

        factcheck_decision = score_and_decide(claim, factcheck_config, input_factcheck_document)
        if should_try_trusted_research(factcheck_decision):
            trace.fallbacks_used.append("trusted_research_after_factcheck_uncertain")
            research_decision = score_and_decide(claim, research_config)
            if should_use_trusted_research(research_decision):
                trace.fallbacks_used.append("trusted_research_fallback_used")
                research_decision.reasons.append("strategy=trusted_research_fallback")
                decisions.append(research_decision)
                continue
        decisions.append(factcheck_decision)

    return finalize_result(decisions, trace=trace, config=config)


def _news_credibility_result(
    article_text: str,
    url: str,
    fetched: dict,
    config: PipelineConfig,
    trace: FactCheckTrace,
) -> FactCheckResult:
    return analyze_news_credibility(article_text, url, fetched, config, trace)


def run_factcheck(
    text: str = "",
    url: str = "",
    fast_mode: bool | None = None,
    mode: str | None = None,
    config: PipelineConfig | None = None,
) -> FactCheckResult:
    """Run the one public best-accuracy product pipeline.

    ``fast_mode`` and ``mode`` are intentionally ignored for backward
    compatibility. The orchestrator chooses internal strategies automatically:
    explicit fact-check verdicts, news credibility, or common-knowledge checks.
    """
    config = config or build_config()
    cache = get_cache()
    trace = FactCheckTrace(mode="best_accuracy")
    start_total = time.perf_counter()
    article_text = canonicalize_text(text)

    try:
        raw_url = (url or "").strip()
        if raw_url:
            start_ingest = time.perf_counter()
            if not is_likely_article_url(raw_url):
                trace.filtered_urls.append({"url": raw_url, "reason": "non_article_input_url"})
                trace.fallbacks_used.append("non_article_input_url")
                fetched = {
                    "text": article_text,
                    "title": "",
                    "url": raw_url,
                    "fetch_source": "non_article_url",
                    "published_at": "",
                    "author": "",
                    "canonical_article_url": raw_url,
                }
                result = _news_credibility_result(article_text, raw_url, fetched, config, trace)
                trace.stage_timings_ms["ingest"] = (time.perf_counter() - start_ingest) * 1000
                return result

            fetched = fetch_url_text(raw_url, cache=cache)
            article_text = canonicalize_text(fetched.get("text", "") or article_text)
            final_url = fetched.get("url", raw_url) or raw_url
            profile = classify_source(final_url)
            if fetched.get("fetch_source") != "direct":
                trace.fallbacks_used.append(f"input_fetch:{fetched.get('fetch_source')}")
            trace.stage_timings_ms["ingest"] = (time.perf_counter() - start_ingest) * 1000

            if profile.source_type == "factcheck_org" or fetched.get("is_factcheck_article"):
                factcheck_text = canonicalize_text(
                    fetched.get("claim_text", "") or fetched.get("text", "") or fetched.get("title", "") or article_text
                )
                input_document = _input_factcheck_document(fetched, raw_url)
                result = _run_claim_verdict_path(factcheck_text, config, trace, cache, input_document)
                return result

            if is_news_source_url(final_url) or profile.source_type in {
                "unknown",
                "low_trust",
                "social",
                "institutional",
                "major_news",
                "primary_news",
            }:
                result = _news_credibility_result(article_text, raw_url, fetched, config, trace)
                return result

        if not article_text:
            return _uncertain_result(
                "No article text was provided and the URL could not be fetched.",
                trace,
                config,
            )

        if _looks_like_simple_knowledge_text(article_text):
            result = _run_claim_verdict_path(article_text, config, trace, cache)
            return result

        if len(article_text) >= 350:
            fetched = {
                "text": article_text,
                "title": "",
                "url": raw_url,
                "fetch_source": "text_input",
                "published_at": "",
                "author": "",
                "canonical_article_url": raw_url,
            }
            result = _news_credibility_result(article_text, raw_url, fetched, config, trace)
            return result

        result = _run_claim_verdict_path(article_text, config, trace, cache)
        return result
    finally:
        trace.stage_timings_ms["total"] = (time.perf_counter() - start_total) * 1000
