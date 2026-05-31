from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


def _round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


@dataclass
class ConfigSnapshot:
    pipeline_version: str
    mode: str
    fast_mode: bool
    max_claims: int
    max_documents: int
    max_evidence: int
    hard_min_independent: int
    hard_min_trusted: int
    decision_margin: float
    prior_probability_threshold: float = 0.0
    prior_margin_threshold: float = 0.0
    model_versions: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClaimCandidate:
    raw_text: str
    normalized_text: str
    score: float
    entities: List[str] = field(default_factory=list)
    dates: List[str] = field(default_factory=list)
    numbers: List[str] = field(default_factory=list)
    source: str = "article"

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["score"] = _round(self.score)
        return payload


@dataclass
class RetrievedDocument:
    query: str
    url: str
    canonical_url: str
    title: str
    snippet: str
    content: str
    source_url: str
    source_type: str
    source_trust: float
    domain: str
    retrieval_score: float
    fetch_source: str = "direct"
    published_at: str = ""
    author: str = ""
    canonical_article_url: str = ""
    is_factcheck_article: bool = False
    explicit_verdict: str = ""
    explicit_verdict_label: str = ""
    verdict_source: str = ""
    claim_text: str = ""
    ruling_text: str = ""
    claim_match_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["source_trust"] = _round(self.source_trust)
        payload["retrieval_score"] = _round(self.retrieval_score)
        payload["claim_match_score"] = _round(self.claim_match_score)
        return payload


@dataclass
class EvidenceItem:
    url: str
    title: str
    stance: str
    score: float
    snippet: str
    passage: str
    source_type: str
    source_trust: float
    relevance: float
    freshness: float
    domain: str
    is_factcheck_article: bool = False
    explicit_verdict: str = ""
    verdict_source: str = ""
    claim_match_score: float = 0.0

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "stance": self.stance,
            "score": _round(self.score),
            "snippet": self.snippet,
            "passage": self.passage,
            "source_type": self.source_type,
            "source_trust": _round(self.source_trust),
            "relevance": _round(self.relevance),
            "freshness": _round(self.freshness),
            "domain": self.domain,
            "claim_match_score": _round(self.claim_match_score),
            "verdict_source": self.verdict_source,
        }


@dataclass
class ClaimDecision:
    claim: ClaimCandidate
    verdict: str
    confidence: float
    support_score: float
    refute_score: float
    neutral_score: float
    independent_sources: int
    trusted_hits: int
    reasons: List[str] = field(default_factory=list)
    evidence: List[EvidenceItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim.to_dict(),
            "verdict": self.verdict,
            "confidence": _round(self.confidence),
            "support_score": _round(self.support_score),
            "refute_score": _round(self.refute_score),
            "neutral_score": _round(self.neutral_score),
            "independent_sources": self.independent_sources,
            "trusted_hits": self.trusted_hits,
            "reasons": list(self.reasons),
            "evidence": [item.to_public_dict() for item in self.evidence],
        }


@dataclass
class CredibilityResult:
    score: float
    label: str
    source_score: float
    article_quality_score: float
    corroboration_score: float
    risk_score: float
    matched_sources: List[Dict[str, Any]] = field(default_factory=list)
    risk_flags: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": _round(self.score),
            "label": self.label,
            "source_score": _round(self.source_score),
            "article_quality_score": _round(self.article_quality_score),
            "corroboration_score": _round(self.corroboration_score),
            "risk_score": _round(self.risk_score),
            "matched_sources": list(self.matched_sources),
            "risk_flags": list(self.risk_flags),
            "reasons": list(self.reasons),
        }


@dataclass
class ImageAnalysisResult:
    mode: str
    ocr_text: str = ""
    ocr_confidence: float = 0.0
    detected_urls: List[str] = field(default_factory=list)
    ai_generated_score: float = 0.0
    ai_label: str = "not_evaluated"
    warnings: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "ocr_text": self.ocr_text,
            "ocr_confidence": _round(self.ocr_confidence),
            "detected_urls": list(self.detected_urls),
            "ai_generated_score": _round(self.ai_generated_score),
            "ai_label": self.ai_label,
            "warnings": list(self.warnings),
            "reasons": list(self.reasons),
            "metadata": dict(self.metadata),
        }


@dataclass
class FactCheckTrace:
    mode: str = ""
    queries: List[str] = field(default_factory=list)
    filtered_urls: List[Dict[str, str]] = field(default_factory=list)
    selected_passages: List[Dict[str, Any]] = field(default_factory=list)
    decision_reasons: List[str] = field(default_factory=list)
    fallbacks_used: List[str] = field(default_factory=list)
    stage_timings_ms: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "pipeline": self.mode,
            "queries": list(self.queries),
            "filtered_urls": list(self.filtered_urls),
            "selected_passages": list(self.selected_passages),
            "decision_reasons": list(self.decision_reasons),
            "fallbacks_used": list(self.fallbacks_used),
            "stage_timings_ms": {k: _round(v, 2) for k, v in self.stage_timings_ms.items()},
        }


@dataclass
class FactCheckResult:
    verdict: str
    confidence: float
    summary: str
    claim: str
    evidence: List[EvidenceItem] = field(default_factory=list)
    trace: FactCheckTrace = field(default_factory=FactCheckTrace)
    claims: List[ClaimDecision] = field(default_factory=list)
    config: ConfigSnapshot | None = None
    pipeline_version: str = ""
    credibility: CredibilityResult | None = None
    image_analysis: ImageAnalysisResult | None = None

    def to_public_dict(self) -> Dict[str, Any]:
        payload = {
            "verdict": self.verdict,
            "confidence": _round(self.confidence),
            "summary": self.summary,
            "claim": self.claim,
            "evidence": [item.to_public_dict() for item in self.evidence],
            "credibility": self.credibility.to_dict() if self.credibility is not None else None,
            "image_analysis": self.image_analysis.to_dict() if self.image_analysis is not None else None,
            "trace": self.trace.to_dict(),
            "pipeline_version": self.pipeline_version,
        }
        if self.config is not None:
            payload["config"] = self.config.to_dict()
        if self.claims:
            payload["claims"] = [claim.to_dict() for claim in self.claims]
        return payload
