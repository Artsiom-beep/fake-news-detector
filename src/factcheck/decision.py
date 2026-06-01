from __future__ import annotations

from typing import List

from .config import HARD_TRUSTED_TYPES, PipelineConfig
from .schemas import ClaimCandidate, ClaimDecision, EvidenceItem, FactCheckResult, FactCheckTrace

ATTRIBUTION_DOMAIN_HINTS = {
    "reuters": "reuters.com",
    "associated press": "apnews.com",
    "ap reported": "apnews.com",
    "afp": "afp.com",
    "bbc": "bbc.com",
    "factcheck.org": "factcheck.org",
    "snopes": "snopes.com",
    "politifact": "politifact.com",
    "boomlive": "boomlive.in",
    "newschecker": "newschecker.in",
    "who": "who.int",
    "cdc": "cdc.gov",
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def select_safe_prior_prediction(*args, **kwargs):
    try:
        from .claim_prior import select_safe_prior_prediction as _select_safe_prior_prediction
    except Exception:
        return None
    return _select_safe_prior_prediction(*args, **kwargs)


def _summarize(verdict: str, claim_text: str, evidence: List[EvidenceItem]) -> str:
    if verdict == "true":
        relevant_evidence = [item for item in evidence if item.stance == "support"]
    elif verdict == "fake":
        relevant_evidence = [item for item in evidence if item.stance == "refute"]
    else:
        relevant_evidence = evidence
    domains = [item.domain for item in relevant_evidence[:2] if item.domain]
    domains_text = ", ".join(domains) if domains else "retrieved sources"
    if not evidence and verdict in {"true", "fake"}:
        return (
            f"No strong source evidence was found for this claim; the fallback claim-prior model predicts it is likely "
            f"{verdict}: {claim_text}"
        )
    if verdict == "true":
        return f"Evidence from {domains_text} supports the claim: {claim_text}"
    if verdict == "fake":
        return f"Evidence from {domains_text} refutes the claim: {claim_text}"
    if evidence:
        if any(item.source_type in {"common_knowledge", "knowledge_source", "local_arithmetic"} for item in evidence):
            return f"No exact answer was found in the available knowledge sources for the claim: {claim_text}"
        return f"Evidence for the claim is limited or conflicting; the strongest matches came from {domains_text}."
    return "No exact answer was found in the available sources for this claim."


def _attributed_domain(claim_text: str) -> str:
    low = (claim_text or "").lower()
    for marker, domain in ATTRIBUTION_DOMAIN_HINTS.items():
        if marker in low:
            return domain
    return ""


def decide_claim(
    claim: ClaimCandidate,
    evidence: List[EvidenceItem],
    trace: FactCheckTrace,
    config: PipelineConfig,
) -> ClaimDecision:
    if config.mode == "factcheck_only":
        return decide_claim_factcheck_only(claim, evidence, trace=trace, config=config)

    support_items = [item for item in evidence if item.stance == "support"]
    refute_items = [item for item in evidence if item.stance == "refute"]
    neutral_items = [item for item in evidence if item.stance == "neutral"]

    support_score = sum(item.score for item in support_items)
    refute_score = sum(item.score for item in refute_items)
    neutral_score = sum(item.score for item in neutral_items)

    dominant_items = support_items if support_score >= refute_score else refute_items
    dominant_label = "true" if support_score >= refute_score else "fake"
    dominant_score = max(support_score, refute_score)
    counter_score = min(support_score, refute_score)
    independent_sources = len({item.domain for item in dominant_items if item.domain})
    trusted_hits = sum(1 for item in dominant_items if item.source_type in HARD_TRUSTED_TYPES)
    margin = dominant_score - counter_score
    max_claim_match = max((item.claim_match_score for item in evidence), default=0.0)
    dominant_claim_match = max((item.claim_match_score for item in dominant_items), default=0.0)

    reasons = [
        f"support_score={support_score:.3f}",
        f"refute_score={refute_score:.3f}",
        f"neutral_score={neutral_score:.3f}",
        f"independent_sources={independent_sources}",
        f"trusted_hits={trusted_hits}",
        f"margin={margin:.3f}",
        f"max_claim_match={max_claim_match:.3f}",
    ]

    hard_verdict_allowed = (
        dominant_score >= config.min_dominant_score
        and independent_sources >= config.hard_min_independent
        and trusted_hits >= config.hard_min_trusted
        and margin >= config.decision_margin
        and dominant_score >= max(counter_score * 1.22, counter_score + config.decision_margin)
    )

    attributed_domain = _attributed_domain(claim.normalized_text)
    attributed_match = [
        item
        for item in dominant_items
        if attributed_domain and item.domain.endswith(attributed_domain) and item.source_type in HARD_TRUSTED_TYPES
    ]
    attributed_threshold = 0.52 if config.fast_mode else 0.74
    attributed_override = (
        not hard_verdict_allowed
        and bool(attributed_match)
        and max(item.score for item in attributed_match) >= attributed_threshold
        and counter_score <= 0.24
    )
    explicit_factcheck_items = [
        item
        for item in dominant_items
        if item.is_factcheck_article
        and (item.source_type == "factcheck_org" or item.source_trust >= 0.75)
        and item.verdict_source
        and item.claim_match_score >= 0.52
    ]
    explicit_factcheck_override = (
        not hard_verdict_allowed
        and bool(explicit_factcheck_items)
        and max(item.score for item in explicit_factcheck_items) >= 0.78
        and counter_score <= 0.18
    )
    model_stance_items = [
        item
        for item in dominant_items
        if item.stance_method.startswith("model:")
        and item.stance_confidence >= 0.78
        and item.score >= 0.76
        and item.claim_match_score >= 0.42
        and (
            item.source_type in HARD_TRUSTED_TYPES
            or (item.source_type == "major_news" and item.source_trust >= 0.84 and item.claim_match_score >= 0.55)
        )
    ]
    model_stance_override = (
        not hard_verdict_allowed
        and bool(model_stance_items)
        and counter_score <= 0.18
        and neutral_score <= max(0.95, dominant_score * 1.35)
    )
    prior_prediction = None
    low_evidence_case = not evidence or (dominant_score < 0.28 and trusted_hits == 0 and independent_sources == 0)
    weak_match_case = bool(evidence) and max_claim_match < 0.30 and dominant_score < 0.70
    low_evidence_case = low_evidence_case or weak_match_case
    neutral_only_case = bool(evidence) and neutral_score > 0 and support_score == 0 and refute_score == 0
    single_trusted_consensus_case = (
        bool(dominant_items)
        and independent_sources == 1
        and trusted_hits >= 1
        and dominant_score >= max(0.78, config.min_dominant_score + 0.12)
        and counter_score <= 0.22
        and dominant_claim_match >= 0.42
    )
    if config.allow_prior_fallback and (low_evidence_case or single_trusted_consensus_case) and not neutral_only_case:
        prior_prediction = select_safe_prior_prediction(
            claim.normalized_text,
            probability_threshold=config.prior_probability_threshold,
            margin_threshold=config.prior_margin_threshold,
        )

    if hard_verdict_allowed:
        verdict = dominant_label
        confidence = _clamp(
            0.52
            + 0.18 * min(1.0, dominant_score)
            + 0.09 * min(2, independent_sources - 1)
            + 0.08 * min(2, trusted_hits)
            + 0.10 * min(1.0, margin),
            0.55,
            0.92,
        )
        reasons.append("hard_verdict_policy=passed")
    elif attributed_override:
        verdict = dominant_label
        confidence = _clamp(0.54 + 0.12 * max(item.score for item in attributed_match), 0.56, 0.74)
        reasons.append(f"hard_verdict_policy=attribution_override:{attributed_domain}:{dominant_label}")
    elif explicit_factcheck_override:
        strongest = max(explicit_factcheck_items, key=lambda item: (item.score, item.claim_match_score))
        verdict = dominant_label
        confidence = _clamp(
            0.58
            + 0.09 * min(1.0, strongest.score)
            + 0.08 * min(1.0, strongest.claim_match_score)
            + 0.04 * min(1.0, margin),
            0.6,
            0.82,
        )
        reasons.append(
            "hard_verdict_policy=explicit_factcheck_override:"
            f"{strongest.domain}:{strongest.verdict_source}:{strongest.claim_match_score:.3f}"
        )
    elif model_stance_override:
        strongest = max(model_stance_items, key=lambda item: (item.stance_confidence, item.score, item.claim_match_score))
        verdict = dominant_label
        confidence = _clamp(
            0.50
            + 0.12 * min(1.0, strongest.stance_confidence)
            + 0.08 * min(1.0, strongest.score)
            + 0.08 * min(1.0, strongest.claim_match_score)
            + 0.04 * min(1.0, strongest.source_trust),
            0.58,
            0.76,
        )
        reasons.append(
            "hard_verdict_policy=model_stance_override:"
            f"{strongest.domain}:{strongest.stance_method}:{strongest.stance_confidence:.3f}:"
            f"{strongest.claim_match_score:.3f}"
        )
    elif (
        prior_prediction is not None
        and single_trusted_consensus_case
        and prior_prediction.label == dominant_label
    ):
        verdict = dominant_label
        confidence = _clamp(
            0.54
            + 0.10 * min(1.0, dominant_score)
            + 0.10 * min(1.0, prior_prediction.confidence)
            + 0.08 * min(1.0, prior_prediction.margin),
            0.56,
            0.72,
        )
        reasons.append(
            "hard_verdict_policy=single_trusted_consensus:"
            f"{dominant_label}:{prior_prediction.confidence:.3f}:{prior_prediction.margin:.3f}"
        )
    elif prior_prediction is not None and low_evidence_case:
        verdict = prior_prediction.label
        confidence = _clamp(
            0.45
            + 0.18 * min(1.0, prior_prediction.confidence)
            + 0.12 * min(1.0, prior_prediction.margin),
            0.48,
            0.66,
        )
        reasons.append(
            "hard_verdict_policy=claim_prior_fallback:"
            f"{prior_prediction.label}:{prior_prediction.confidence:.3f}:{prior_prediction.margin:.3f}"
        )
    else:
        verdict = "uncertain"
        confidence = _clamp(
            0.24 + 0.18 * min(1.0, dominant_score) + 0.08 * min(1.0, margin),
            0.2,
            0.58,
        )
        reasons.append("hard_verdict_policy=blocked")

    trace.decision_reasons.extend([f"{claim.normalized_text}: {reason}" for reason in reasons])
    return ClaimDecision(
        claim=claim,
        verdict=verdict,
        confidence=confidence,
        support_score=support_score,
        refute_score=refute_score,
        neutral_score=neutral_score,
        independent_sources=independent_sources,
        trusted_hits=trusted_hits,
        reasons=reasons,
        evidence=evidence,
    )


def decide_claim_factcheck_only(
    claim: ClaimCandidate,
    evidence: List[EvidenceItem],
    trace: FactCheckTrace,
    config: PipelineConfig,
) -> ClaimDecision:
    explicit_items = [
        item
        for item in evidence
        if item.is_factcheck_article
        and (item.source_type == "factcheck_org" or item.source_trust >= 0.75)
        and item.explicit_verdict in {"support", "refute"}
        and item.claim_match_score >= 0.52
    ]
    support_items = [item for item in explicit_items if item.stance == "support"]
    refute_items = [item for item in explicit_items if item.stance == "refute"]
    support_score = sum(item.score for item in support_items)
    refute_score = sum(item.score for item in refute_items)
    neutral_score = sum(item.score for item in evidence if item.stance == "neutral")
    reasons = [
        "strategy=explicit_factcheck",
        f"explicit_factcheck_items={len(explicit_items)}",
        f"support_score={support_score:.3f}",
        f"refute_score={refute_score:.3f}",
    ]

    if support_items and refute_items:
        verdict = "uncertain"
        confidence = 0.42
        chosen_items = sorted(explicit_items, key=lambda item: item.score, reverse=True)
        reasons.append("hard_verdict_policy=blocked_conflicting_explicit_verdicts")
        trace.fallbacks_used.append("conflicting_explicit_factcheck_verdicts")
    elif support_items or refute_items:
        chosen_items = sorted(support_items or refute_items, key=lambda item: item.score, reverse=True)
        strongest = chosen_items[0]
        verdict = "true" if support_items else "fake"
        confidence = _clamp(
            0.55
            + 0.12 * min(1.0, strongest.source_trust)
            + 0.13 * min(1.0, strongest.claim_match_score)
            + 0.05 * min(1.0, strongest.score),
            0.60,
            0.85,
        )
        reasons.append(
            "hard_verdict_policy=explicit_factcheck_only:"
            f"{strongest.domain}:{strongest.verdict_source or 'explicit_verdict'}:"
            f"{strongest.claim_match_score:.3f}"
        )
    else:
        verdict = "uncertain"
        confidence = 0.24 if not evidence else 0.34
        chosen_items = sorted(evidence, key=lambda item: item.score, reverse=True)
        reasons.append("hard_verdict_policy=no_explicit_factcheck_verdict")
        trace.fallbacks_used.append("no_explicit_factcheck_verdict")

    independent_sources = len({item.domain for item in chosen_items if item.domain})
    trusted_hits = sum(1 for item in chosen_items if item.source_type in HARD_TRUSTED_TYPES)
    trace.decision_reasons.extend([f"{claim.normalized_text}: {reason}" for reason in reasons])
    return ClaimDecision(
        claim=claim,
        verdict=verdict,
        confidence=confidence,
        support_score=support_score,
        refute_score=refute_score,
        neutral_score=neutral_score,
        independent_sources=independent_sources,
        trusted_hits=trusted_hits,
        reasons=reasons,
        evidence=chosen_items[: config.max_evidence],
    )


def finalize_result(
    decisions: List[ClaimDecision],
    trace: FactCheckTrace,
    config: PipelineConfig,
) -> FactCheckResult:
    if not decisions:
        return FactCheckResult(
            verdict="uncertain",
            confidence=0.2,
            summary="No checkable claim was found in the provided input.",
            claim="",
            evidence=[],
            trace=trace,
            claims=[],
            config=config.snapshot(),
            pipeline_version=config.pipeline_version,
        )

    primary = max(
        decisions,
        key=lambda item: (
            max(item.support_score, item.refute_score),
            item.claim.score,
        ),
    )

    strong_opposite = [
        item
        for item in decisions
        if item is not primary
        and item.verdict in {"true", "fake"}
        and item.verdict != primary.verdict
        and item.confidence >= 0.58
    ]
    if strong_opposite and primary.verdict != "uncertain":
        trace.decision_reasons.append("primary_claim_overridden=conflicting_secondary_claims")
        primary = ClaimDecision(
            claim=primary.claim,
            verdict="uncertain",
            confidence=min(primary.confidence, 0.52),
            support_score=primary.support_score,
            refute_score=primary.refute_score,
            neutral_score=primary.neutral_score,
            independent_sources=primary.independent_sources,
            trusted_hits=primary.trusted_hits,
            reasons=primary.reasons + ["conflicting secondary claim signals"],
            evidence=primary.evidence,
        )

    summary = _summarize(primary.verdict, primary.claim.normalized_text, primary.evidence)
    return FactCheckResult(
        verdict=primary.verdict,
        confidence=primary.confidence,
        summary=summary,
        claim=primary.claim.normalized_text,
        evidence=primary.evidence,
        trace=trace,
        claims=decisions,
        config=config.snapshot(),
        pipeline_version=config.pipeline_version,
    )
