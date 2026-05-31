from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

import requests

from .claims import extract_claims
from .config import PipelineConfig
from .ingest import canonicalize_text, canonicalize_url, is_likely_article_url
from .retrieval import search_web
from .schemas import CredibilityResult, EvidenceItem, FactCheckResult, FactCheckTrace
from .source_registry import classify_source

TRUSTED_CORROBORATION_TYPES = {"primary_news", "major_news", "institutional", "factcheck_org"}
SENSATIONAL_MARKERS = {
    "shocking",
    "bombshell",
    "you won't believe",
    "secret plot",
    "miracle cure",
    "exposed",
    "cover-up",
    "coverup",
    "urgent",
    "breaking!!!",
}

SOURCE_SUFFIXES = {
    "abc news",
    "afp",
    "al jazeera",
    "ap",
    "ap news",
    "associated press",
    "bbc",
    "bbc news",
    "cbs news",
    "dw",
    "france 24",
    "guardian",
    "nbc news",
    "npr",
    "reuters",
    "sky news",
    "the guardian",
}

SOURCE_ARTICLE_RESOLUTION_DOMAINS = {
    "abcnews.go.com",
    "abcnews.com",
    "aljazeera.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "cbsnews.com",
    "france24.com",
    "nbcnews.com",
    "npr.org",
    "reuters.com",
    "theguardian.com",
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _tokens(text: str) -> set[str]:
    stop = {
        "the", "and", "for", "with", "from", "that", "this", "are", "was", "were", "has",
        "have", "had", "said", "says", "will", "about", "into", "after", "before", "what",
        "when", "where", "which", "their", "there", "been", "being", "over",
    }
    return {token for token in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(token) > 2 and token not in stop}


def _token_overlap(a: str, b: str) -> float:
    left = _tokens(a)
    right = _tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), 1)


def clean_news_title(title: str) -> str:
    cleaned = canonicalize_text(title)
    if not cleaned:
        return ""
    if cleaned.startswith("Title: ") and " URL Source:" in cleaned:
        cleaned = cleaned.split(" URL Source:", 1)[0].replace("Title: ", "", 1).strip()
    cleaned = re.sub(r"^\d+\s+min\s+read\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bCopyright\s+\d{4}.*$", "", cleaned, flags=re.IGNORECASE).strip()
    for separator in (" | ", " - ", " : "):
        if separator not in cleaned:
            continue
        parts = [part.strip() for part in cleaned.split(separator) if part.strip()]
        if len(parts) < 2:
            continue
        tail = re.sub(r"^the\s+", "", parts[-1].lower())
        tail_tokens = re.findall(r"[a-z0-9]+", tail)
        looks_like_section = separator in {" | ", " : "} and len(tail_tokens) <= 7
        if tail in SOURCE_SUFFIXES or looks_like_section:
            cleaned = separator.join(parts[:-1]).strip()
    while " : " in cleaned:
        parts = [part.strip() for part in cleaned.split(" : ") if part.strip()]
        tail_tokens = re.findall(r"[a-z0-9]+", parts[-1].lower()) if parts else []
        if len(parts) < 2 or len(tail_tokens) > 7:
            break
        cleaned = " : ".join(parts[:-1]).strip()
    cleaned = re.sub(r"^(photos?|pictures?|video):\s*", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip(" -|")


def _title_from_url(url: str) -> str:
    try:
        path = urlparse(url or "").path.strip("/")
        tail = path.split("/")[-1] if path else ""
        if not tail or tail.lower() in {"index.html", "index"}:
            return ""
        tail = re.sub(r"\.(html?|amp)$", "", tail, flags=re.IGNORECASE)
        tail = re.sub(r"\b\d{6,}\b", "", tail)
        title = re.sub(r"[-_]+", " ", tail).strip()
        return clean_news_title(title)
    except Exception:
        return ""


def is_news_source_url(url: str) -> bool:
    profile = classify_source(url)
    return profile.source_type in {"primary_news", "major_news", "institutional"}


def _source_score(url: str) -> float:
    profile = classify_source(url)
    if profile.source_type == "primary_news":
        return _clamp(profile.trust)
    if profile.source_type == "institutional":
        return _clamp(profile.trust)
    if profile.source_type == "major_news":
        return _clamp(profile.trust * 0.95)
    if profile.source_type == "factcheck_org":
        return _clamp(profile.trust * 0.92)
    if profile.source_type == "unknown":
        return 0.42
    if profile.source_type == "low_trust":
        return 0.18
    if profile.source_type == "social":
        return 0.08
    return _clamp(profile.trust)


def _article_quality_score(url: str, fetched_article: dict[str, Any], article_text: str) -> tuple[float, list[str]]:
    risk_flags: list[str] = []
    title = fetched_article.get("title", "")
    published_at = fetched_article.get("published_at", "")
    author = fetched_article.get("author", "")
    text_len = len(article_text or "")
    score = 0.0

    if is_likely_article_url(url):
        score += 0.18
    else:
        risk_flags.append("listing_or_non_article_url")
    if title:
        score += 0.18
    else:
        risk_flags.append("missing_title")
    if text_len >= 700:
        score += 0.24
    elif text_len >= 250:
        score += 0.14
    else:
        risk_flags.append("missing_article_text")
    if published_at:
        score += 0.18
    else:
        risk_flags.append("missing_date")
    if author:
        score += 0.08
    else:
        risk_flags.append("missing_author")
    if fetched_article.get("fetch_source") == "direct":
        score += 0.14
    else:
        risk_flags.append(f"fetch_fallback:{fetched_article.get('fetch_source', 'unknown')}")

    return _clamp(score), risk_flags


def _risk_score(url: str, title: str, risk_flags: list[str]) -> tuple[float, list[str]]:
    profile = classify_source(url)
    flags = list(risk_flags)
    low_title = (title or "").lower()
    if profile.source_type == "social":
        flags.append("social_source")
    if profile.source_type == "low_trust":
        flags.append("low_trust_source")
    if profile.source_type == "unknown":
        flags.append("unknown_source")
    if any(marker in low_title for marker in SENSATIONAL_MARKERS):
        flags.append("sensational_language")

    weights = {
        "listing_or_non_article_url": 0.28,
        "missing_article_text": 0.28,
        "missing_date": 0.16,
        "missing_author": 0.07,
        "missing_title": 0.14,
        "social_source": 0.45,
        "low_trust_source": 0.34,
        "unknown_source": 0.22,
        "sensational_language": 0.22,
    }
    score = 0.0
    for flag in flags:
        score += weights.get(flag, 0.08 if flag.startswith("fetch_fallback") else 0.05)
    return _clamp(score), flags


def _extract_main_claims(article_text: str, title: str, max_claims: int = 3) -> list[str]:
    candidates: list[str] = []
    title = clean_news_title(title)
    if title:
        candidates.append(title)
    if not title and (article_text or "").startswith("Title: ") and " URL Source:" in article_text:
        inferred_title = clean_news_title(article_text)
        if inferred_title:
            title = inferred_title
            candidates.append(inferred_title)
    lead = " ".join(re.split(r"(?<=[.!?])\s+", article_text or "")[:2])
    for claim in extract_claims(f"{title}. {lead}", max_claims=max_claims + 2):
        if claim.normalized_text and claim.normalized_text not in candidates:
            candidates.append(claim.normalized_text)
    return candidates[:max_claims]


def _is_google_news_proxy(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.netloc.lower().endswith("news.google.com")


def _resolve_google_news_proxy(url: str) -> str:
    if not _is_google_news_proxy(url):
        return url
    try:
        response = requests.get(
            url,
            timeout=5,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resolved = canonicalize_url(response.url)
        if resolved and not _is_google_news_proxy(resolved) and is_likely_article_url(resolved):
            return resolved
    except Exception:
        return url
    return url


def _resolve_article_from_source_search(claim: str, title: str, domain: str) -> str:
    if not domain or domain not in SOURCE_ARTICLE_RESOLUTION_DOMAINS:
        return ""
    query_seed = clean_news_title(title) or clean_news_title(claim)
    if not query_seed:
        return ""
    for hit in search_web(f"{query_seed} site:{domain}", count=2):
        candidate = canonicalize_url(hit.get("url", ""))
        if candidate and is_likely_article_url(candidate) and classify_source(candidate).domain == domain:
            return candidate
    return ""


def _article_like_evidence_url(hit: dict[str, Any], claim: str):
    article_url = canonicalize_url(hit.get("url", ""))
    source_url = canonicalize_url(hit.get("source_url", ""))
    resolved_article_url = _resolve_google_news_proxy(article_url)
    profile = classify_source(source_url or resolved_article_url)
    if _is_google_news_proxy(resolved_article_url):
        source_article_url = _resolve_article_from_source_search(claim, hit.get("title", ""), profile.domain)
        if source_article_url:
            return source_article_url, classify_source(source_article_url)
    if resolved_article_url and (
        _is_google_news_proxy(resolved_article_url) or is_likely_article_url(resolved_article_url)
    ):
        return resolved_article_url, profile
    if source_url and is_likely_article_url(source_url):
        return source_url, profile
    return article_url or source_url, profile


def _query_variants(claim: str) -> list[str]:
    base = re.sub(r"\s+", " ", clean_news_title(claim)).strip()
    if not base:
        return []
    variants = [base]
    hinted = f"{base} Reuters AP BBC"
    if hinted != base:
        variants.append(hinted)
    return variants


def _corroborate_claims(
    claims: list[str],
    source_url: str,
    config: PipelineConfig,
    trace: FactCheckTrace,
) -> tuple[float, list[dict[str, Any]], list[EvidenceItem]]:
    source_domain = classify_source(source_url).domain
    matched: dict[str, dict[str, Any]] = {}
    evidence: list[EvidenceItem] = []
    max_hits = max(3, min(config.max_search_results, 6))

    for claim in claims:
        if not claim:
            continue
        for query in _query_variants(claim):
            trace.queries.append(query)
            for hit in search_web(query, count=max_hits):
                hit_url, profile = _article_like_evidence_url(hit, claim)
                if not hit_url or profile.source_type not in TRUSTED_CORROBORATION_TYPES:
                    continue
                if source_domain and profile.domain == source_domain:
                    continue
                clean_title = clean_news_title(hit.get("title", ""))
                haystack = " ".join([clean_title, hit.get("snippet", "")])
                relevance = max(_token_overlap(claim, clean_title), _token_overlap(claim, haystack))
                if relevance < 0.24:
                    continue
                score = _clamp(0.35 * relevance + 0.45 * profile.trust + 0.20)
                previous = matched.get(profile.domain)
                if previous and previous["score"] >= score:
                    continue
                matched[profile.domain] = {
                    "domain": profile.domain,
                    "url": hit_url,
                    "title": clean_title or hit_url,
                    "score": round(score, 4),
                    "source_type": profile.source_type,
                    "source_trust": round(profile.trust, 4),
                    "claim": claim,
                }

    for item in sorted(matched.values(), key=lambda value: value["score"], reverse=True)[: config.max_evidence]:
        evidence.append(
            EvidenceItem(
                url=item["url"],
                title=item["title"],
                stance="support",
                score=float(item["score"]),
                snippet=f"Corroborating source for: {item['claim']}",
                passage=f"{item['domain']} appears to cover the same claim: {item['claim']}",
                source_type=item["source_type"],
                source_trust=float(item.get("source_trust", 0.0)),
                relevance=float(item["score"]),
                freshness=0.7,
                domain=item["domain"],
                claim_match_score=float(item["score"]),
            )
        )

    independent = len(matched)
    if independent >= 3:
        corroboration = 0.92
    elif independent == 2:
        corroboration = 0.76
    elif independent == 1:
        corroboration = 0.48
    else:
        corroboration = 0.0
    return corroboration, sorted(matched.values(), key=lambda value: value["score"], reverse=True), evidence


def _credibility_label(score: float) -> str:
    if score >= 0.72:
        return "high"
    if score >= 0.50:
        return "medium"
    if score >= 0.30:
        return "low"
    return "unknown"


def analyze_news_credibility(
    text: str,
    url: str,
    fetched_article: dict[str, Any],
    config: PipelineConfig,
    trace: FactCheckTrace,
) -> FactCheckResult:
    start = time.perf_counter()
    article_text = canonicalize_text(fetched_article.get("text", "") or text)
    title = clean_news_title(fetched_article.get("title", ""))
    final_url = canonicalize_url(fetched_article.get("url", "") or url)
    if not title:
        title = _title_from_url(final_url or url)
    quality_article = dict(fetched_article)
    quality_article["title"] = title
    profile = classify_source(final_url or url)
    claims = _extract_main_claims(article_text, title)
    main_claim = claims[0] if claims else title or article_text[:180]

    source_score = _source_score(final_url or url)
    article_quality_score, quality_flags = _article_quality_score(final_url or url, quality_article, article_text)
    risk_score, risk_flags = _risk_score(final_url or url, title or main_claim, quality_flags)
    corroboration_score, matched_sources, evidence = _corroborate_claims(claims, final_url or url, config, trace)

    if profile.source_type == "unknown" and len(matched_sources) < 2:
        risk_flags.append("unknown_source_without_two_independent_matches")
        risk_score = _clamp(risk_score + 0.18)
    if not matched_sources:
        risk_flags.append("no_independent_corroboration")
        risk_score = _clamp(risk_score + 0.08)

    score = _clamp(
        0.30 * source_score
        + 0.20 * article_quality_score
        + 0.35 * corroboration_score
        - 0.15 * risk_score
    )
    severe_article_flags = {
        "listing_or_non_article_url",
        "missing_article_text",
        "unknown_source",
        "low_trust_source",
        "social_source",
        "sensational_language",
    }
    trusted_article_floor_value: float | None = None
    if (
        profile.source_type in {"primary_news", "major_news", "institutional"}
        and is_likely_article_url(final_url or url)
        and article_quality_score >= 0.50
        and not (set(risk_flags) & severe_article_flags)
    ):
        floor_by_source_type = {
            "institutional": 0.72,
            "primary_news": 0.64,
            "major_news": 0.50,
        }
        trusted_article_floor_value = floor_by_source_type[profile.source_type]
        if score < trusted_article_floor_value:
            score = trusted_article_floor_value
    if profile.source_type == "unknown" and len(matched_sources) < 2:
        score = min(score, 0.69)
    label = _credibility_label(score)
    reasons = [
        f"source={profile.domain or 'unknown'}:{profile.source_type}:{source_score:.3f}",
        f"article_quality={article_quality_score:.3f}",
        f"corroboration={corroboration_score:.3f}:{len(matched_sources)}_independent_sources",
        f"risk={risk_score:.3f}",
    ]
    if trusted_article_floor_value is not None:
        reasons.append(f"trusted_article_source_quality_floor={trusted_article_floor_value:.3f}")
    trace.decision_reasons.extend([f"news_credibility: {reason}" for reason in reasons])
    trace.stage_timings_ms["news_credibility"] = (time.perf_counter() - start) * 1000

    credibility = CredibilityResult(
        score=score,
        label=label,
        source_score=source_score,
        article_quality_score=article_quality_score,
        corroboration_score=corroboration_score,
        risk_score=risk_score,
        matched_sources=matched_sources,
        risk_flags=sorted(set(risk_flags)),
        reasons=reasons,
    )
    summary = (
        f"News credibility is {label} ({score:.2f}). This is a credibility assessment, "
        "not a definitive true/fake verdict."
    )
    return FactCheckResult(
        verdict="uncertain",
        confidence=score,
        summary=summary,
        claim=main_claim,
        evidence=evidence,
        trace=trace,
        claims=[],
        config=config.snapshot(),
        pipeline_version=config.pipeline_version,
        credibility=credibility,
    )
