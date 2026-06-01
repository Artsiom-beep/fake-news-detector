from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from .cache import SQLiteCache, get_cache
from .config import PipelineConfig
from .ingest import canonicalize_url, fetch_url_text, is_likely_article_url
from .schemas import ClaimCandidate, FactCheckTrace, RetrievedDocument
from .source_registry import classify_source

SEED_PATH = Path("data/factcheck/seed_evidence.jsonl")
POLITIFACT_SEARCH_URL = "https://www.politifact.com/search/"
SITE_SEARCH_ADAPTERS = {
    "politifact.com": ("https://www.politifact.com/search/", "q"),
    "factcheck.org": ("https://www.factcheck.org/", "s"),
    "leadstories.com": ("https://leadstories.com/", "s"),
    "checkyourfact.com": ("https://checkyourfact.com/", "s"),
    "africacheck.org": ("https://africacheck.org/", "s"),
    "altnews.in": ("https://www.altnews.in/", "s"),
    "fullfact.org": ("https://fullfact.org/search/", "q"),
    "apnews.com": ("https://apnews.com/search", "q"),
    "bbc.com": ("https://www.bbc.co.uk/search", "q"),
}
TOKEN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "his",
    "in",
    "into",
    "is",
    "it",
    "its",
    "more",
    "not",
    "of",
    "on",
    "or",
    "said",
    "says",
    "she",
    "than",
    "that",
    "the",
    "their",
    "them",
    "there",
    "they",
    "this",
    "to",
    "was",
    "were",
    "what",
    "when",
    "where",
    "who",
    "will",
    "with",
}
DDG_SITE_FALLBACK_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "afp.com",
    "bbc.com",
    "usatoday.com",
    "abc.net.au",
}
LISTING_PAGE_MARKERS = (
    "search results",
    "archive",
    "archives",
    "category:",
    "tag:",
)
DOMAIN_ALIASES = {
    "bbc.com": {"bbc.com", "bbc.co.uk"},
}
FACTCHECK_ONLY_PREFERRED_DOMAINS = [
    "politifact.com",
    "factcheck.org",
    "snopes.com",
    "leadstories.com",
    "fullfact.org",
    "checkyourfact.com",
    "africacheck.org",
    "factcheck.afp.com",
    "boomlive.in",
    "newschecker.in",
]


def _cache_key(parts: Iterable[str]) -> str:
    material = "||".join(parts)
    return hashlib.sha1(material.encode("utf-8")).hexdigest()


def _normalized_tokens(text: str) -> List[str]:
    tokens = [token for token in re.findall(r"\w+", (text or "").lower()) if len(token) > 1]
    return [token for token in tokens if token not in TOKEN_STOPWORDS]


def _select_safe_prior_prediction(*args, **kwargs):
    try:
        from .claim_prior import select_safe_prior_prediction
    except Exception:
        return None
    return select_safe_prior_prediction(*args, **kwargs)


def _clean_ddg_url(href: str) -> str:
    try:
        if not href:
            return ""
        if "duckduckgo.com/l/?" in href and "uddg=" in href:
            query = parse_qs(urlparse(href).query)
            if "uddg" in query and query["uddg"]:
                return unquote(query["uddg"][0])
        return href
    except Exception:
        return href


def _search_duckduckgo(query: str, count: int = 5) -> List[Dict[str, str]]:
    try:
        response = requests.post(
            "https://duckduckgo.com/html/",
            data={"q": query},
            timeout=6,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.text, "html.parser")
        hits = []
        for anchor in soup.select("a.result__a")[:count]:
            parent = anchor.find_parent("div", class_="result")
            snippet = parent.select_one(".result__snippet").get_text(" ", strip=True) if parent and parent.select_one(".result__snippet") else ""
            hits.append(
                {
                    "title": anchor.get_text(" ", strip=True),
                    "url": _clean_ddg_url(anchor.get("href", "")),
                    "snippet": snippet,
                    "published_at": "",
                }
            )
        return hits
    except Exception:
        return []


def _search_google_news_rss(query: str, count: int = 5) -> List[Dict[str, str]]:
    try:
        low_query = query.lower()
        if "site:" in low_query or "fact check" in low_query:
            return []
        rss_url = (
            "https://news.google.com/rss/search?"
            f"q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
        )
        response = requests.get(rss_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code != 200 or not response.text:
            return []

        root = ET.fromstring(response.text)
        hits = []
        for item in root.findall(".//item")[:count]:
            title = (item.findtext("title") or "").strip()
            url = (item.findtext("link") or "").strip()
            description = (item.findtext("description") or "").strip()
            source = item.find("source")
            source_url = source.attrib.get("url", "").strip() if source is not None else ""
            pub_date = (item.findtext("pubDate") or "").strip()
            hits.append(
                {
                    "title": title,
                    "url": url,
                    "source_url": source_url,
                    "snippet": description,
                    "published_at": pub_date,
                }
            )
        return hits
    except Exception:
        return []


def _search_politifact_site(query: str, count: int = 5) -> List[Dict[str, str]]:
    try:
        if "site:" in query.lower() and "politifact.com" not in query.lower():
            return []
        response = requests.get(
            POLITIFACT_SEARCH_URL,
            params={"q": query},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response.status_code != 200 or not response.text:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        hits = []
        seen = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if "/factchecks/" not in href or "/factchecks/list/" in href:
                continue
            url = canonicalize_url("https://www.politifact.com" + href if href.startswith("/") else href)
            if not url or url in seen:
                continue
            seen.add(url)
            title = anchor.get_text(" ", strip=True)
            context_node = anchor.find_parent(["article", "li", "div"])
            context_text = context_node.get_text(" ", strip=True) if context_node else title
            snippet = context_text.replace(title, " ", 1).strip()
            hits.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet[:320],
                    "published_at": "",
                }
            )
            if len(hits) >= count:
                break
        return hits
    except Exception:
        return []


def _extract_site_query(query: str) -> tuple[str, str]:
    low = query.lower()
    if " site:" not in f" {low}":
        return "", query
    base, _, domain = low.rpartition(" site:")
    return domain.strip(), query[: len(base)].strip()


def _url_matches_domain(url: str, domain: str) -> bool:
    host = urlparse(url).netloc.lower().replace("www.", "").strip()
    allowed_hosts = DOMAIN_ALIASES.get(domain, {domain})
    return any(host.endswith(candidate) for candidate in allowed_hosts)


def _search_site_adapter(query: str, count: int = 5) -> List[Dict[str, str]]:
    domain, base_query = _extract_site_query(query)
    if not domain or domain not in SITE_SEARCH_ADAPTERS:
        return []
    if domain == "politifact.com":
        return _search_politifact_site(base_query or query, count=count)

    endpoint, param_name = SITE_SEARCH_ADAPTERS[domain]
    try:
        response = requests.get(
            endpoint,
            params={param_name: base_query or query},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response.status_code not in {200, 404} or not response.text:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        hits = []
        seen = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href", "")
            if not href:
                continue
            url = canonicalize_url(
                href if href.startswith("http") else f"https://{domain}{href if href.startswith('/') else '/' + href}"
            )
            if not _url_matches_domain(url, domain) or not is_likely_article_url(url) or url in seen:
                continue
            seen.add(url)
            title = anchor.get_text(" ", strip=True)
            context_node = anchor.find_parent(["article", "li", "div"])
            context_text = context_node.get_text(" ", strip=True) if context_node else title
            snippet = context_text.replace(title, " ", 1).strip()
            if _query_relevance_score(base_query, title, snippet) < 0.12:
                continue
            hits.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet[:320],
                    "published_at": "",
                }
            )
            if len(hits) >= count:
                break
        return hits
    except Exception:
        return []


def _is_supported_site_query_for_ddg(query: str) -> bool:
    domain, _ = _extract_site_query(query)
    return bool(domain and domain in DDG_SITE_FALLBACK_DOMAINS)


def search_web(query: str, count: int = 5, cache: SQLiteCache | None = None) -> List[Dict[str, str]]:
    cache = cache or get_cache()
    key = _cache_key(["search_v6", query, str(count)])
    cached = cache.get("search", key)
    if cached is not None:
        return cached

    hits = []
    seen = set()
    low_query = query.lower()
    site_domain, _ = _extract_site_query(query)
    provider_hits = []

    site_hits = _search_site_adapter(query, count=count)
    if site_hits:
        provider_hits.append(site_hits)
    elif not site_domain and ("fact check" in low_query or "politifact" in low_query):
        politifact_hits = _search_politifact_site(query, count=count)
        if politifact_hits:
            provider_hits.append(politifact_hits)

    if "site:" not in low_query:
        google_hits = _search_google_news_rss(query, count=count)
        if google_hits:
            provider_hits.append(google_hits)

    if not provider_hits and ("site:" not in low_query or _is_supported_site_query_for_ddg(query)):
        ddg_hits = _search_duckduckgo(query, count=count)
        if ddg_hits:
            provider_hits.append(ddg_hits)

    for source_hits in provider_hits:
        for hit in source_hits:
            url = canonicalize_url(hit.get("url", ""))
            if not url or url in seen:
                continue
            seen.add(url)
            payload = dict(hit)
            payload["url"] = url
            hits.append(payload)

    cache.set("search", key, hits)
    return hits


def _rewrite_query(claim: ClaimCandidate) -> str:
    base = re.sub(r"[^a-zA-Z0-9\s\-]", " ", claim.normalized_text.lower())
    stopwords = {
        "the",
        "and",
        "that",
        "this",
        "with",
        "from",
        "have",
        "has",
        "were",
        "was",
        "said",
        "reported",
        "according",
    }
    tokens = [token for token in re.split(r"\s+", base) if len(token) > 2 and token not in stopwords]
    return " ".join(tokens[:10]).strip()


def build_queries(claim: ClaimCandidate, config: PipelineConfig) -> List[str]:
    queries: List[str] = []
    normalized = claim.normalized_text
    if normalized:
        queries.append(normalized)

    entity_tokens = claim.entities[:2] + claim.dates[:1] + claim.numbers[:1]
    if entity_tokens:
        queries.append(" ".join(entity_tokens))

    rewritten = _rewrite_query(claim)
    if rewritten and rewritten not in queries:
        queries.append(rewritten)

    factcheck_query = rewritten or normalized
    if factcheck_query:
        queries.append(f"{factcheck_query} fact check")

    if config.mode == "factcheck_only":
        queries = []
        if factcheck_query:
            queries.append(f"{factcheck_query} fact check")
        prioritized_domains = [
            domain
            for domain in FACTCHECK_ONLY_PREFERRED_DOMAINS
            if domain in config.targeted_domains
        ]
        for domain in prioritized_domains:
            base = rewritten or normalized
            if base:
                queries.append(f"{base} site:{domain}")
        deduped = []
        seen = set()
        for query in queries:
            compact = re.sub(r"\s+", " ", query).strip()
            if not compact or compact in seen:
                continue
            seen.add(compact)
            deduped.append(compact)
        return deduped[:12]

    prioritized_domains = list(config.targeted_domains)
    if config.fast_mode:
        preferred = [
            "politifact.com",
            "factcheck.org",
            "reuters.com",
            "apnews.com",
            "bbc.com",
            "leadstories.com",
            "fullfact.org",
            "snopes.com",
            "checkyourfact.com",
        ]
        prioritized_domains = [domain for domain in preferred if domain in config.targeted_domains]
        prioritized_domains.extend(
            [domain for domain in config.targeted_domains if domain not in prioritized_domains]
        )
        prioritized_domains = prioritized_domains[:7]

    for domain in prioritized_domains:
        base = rewritten or normalized
        if not base:
            continue
        queries.append(f"{base} site:{domain}")

    deduped = []
    seen = set()
    for query in queries:
        compact = re.sub(r"\s+", " ", query).strip()
        if not compact or compact in seen:
            continue
        seen.add(compact)
        deduped.append(compact)
    if config.fast_mode:
        return deduped[:12]
    return deduped


def _select_fast_queries(queries: List[str], prior_label: str = "", clean_claim_live_search: bool = False) -> List[str]:
    plain_queries: List[str] = []
    site_queries: Dict[str, str] = {}
    for query in queries:
        domain, _ = _extract_site_query(query)
        if domain:
            site_queries.setdefault(domain, query)
        else:
            plain_queries.append(query)

    selected: List[str] = []
    if plain_queries:
        selected.append(plain_queries[0])

    for query in plain_queries[1:]:
        if "fact check" in query.lower():
            continue
        if len(query.split()) < 4:
            continue
        if query not in selected:
            selected.append(query)
        break

    factcheck_query = next((query for query in plain_queries if "fact check" in query.lower()), "")
    if factcheck_query and factcheck_query not in selected:
        selected.append(factcheck_query)

    if clean_claim_live_search or prior_label == "true":
        preferred_domains = [
            "reuters.com",
            "apnews.com",
            "bbc.com",
            "afp.com",
            "politifact.com",
            "factcheck.org",
            "fullfact.org",
        ]
    elif prior_label == "fake":
        preferred_domains = [
            "politifact.com",
            "factcheck.org",
            "reuters.com",
            "apnews.com",
            "bbc.com",
            "leadstories.com",
            "fullfact.org",
        ]
    else:
        preferred_domains = [
            "politifact.com",
            "factcheck.org",
            "reuters.com",
            "apnews.com",
            "bbc.com",
            "leadstories.com",
            "fullfact.org",
        ]

    for domain in preferred_domains:
        query = site_queries.get(domain)
        if query and query not in selected:
            selected.append(query)
        if len(selected) >= 9:
            return selected

    for query in plain_queries:
        if query not in selected:
            selected.append(query)
        if len(selected) >= 9:
            return selected
    return selected[:9]


def _result_relevance(claim: ClaimCandidate, title: str, snippet: str) -> float:
    claim_tokens = set(_normalized_tokens(claim.normalized_text))
    doc_tokens = set(_normalized_tokens(f"{title} {snippet}"))
    if not claim_tokens or not doc_tokens:
        return 0.0
    overlap = len(claim_tokens & doc_tokens) / max(len(claim_tokens), 1)
    entity_bonus = 0.2 if any(entity.lower() in f"{title} {snippet}".lower() for entity in claim.entities[:2]) else 0.0
    return min(1.0, overlap + entity_bonus)


def _query_relevance_score(query: str, title: str, snippet: str) -> float:
    query_tokens = set(_normalized_tokens(query))
    doc_tokens = set(_normalized_tokens(f"{title} {snippet}"))
    if not query_tokens or not doc_tokens:
        return 0.0
    return len(query_tokens & doc_tokens) / max(len(query_tokens), 1)


def _claim_match_score(claim: ClaimCandidate, fetched: Dict[str, str], title: str, snippet: str) -> float:
    if fetched.get("explicit_verdict") and fetched.get("claim_text"):
        claim_score = _token_overlap(claim.normalized_text, fetched.get("claim_text", ""))
        if claim_score >= 0.52:
            return claim_score
        secondary_scores = [
            _token_overlap(claim.normalized_text, title),
            _token_overlap(claim.normalized_text, snippet),
            min(_token_overlap(claim.normalized_text, fetched.get("ruling_text", "")), 0.50),
        ]
        return min(0.50, max([claim_score, *secondary_scores]))
    candidates = [
        fetched.get("claim_text", ""),
        title,
        snippet,
        fetched.get("ruling_text", ""),
    ]
    scores = [_token_overlap(claim.normalized_text, candidate) for candidate in candidates if candidate]
    return max(scores) if scores else 0.0


def _load_seed_rows() -> List[Dict[str, str]]:
    if not SEED_PATH.exists():
        return []
    rows: List[Dict[str, str]] = []
    for line in SEED_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def _normalize_seed_text(text: str) -> str:
    text = re.sub(r"[^\w\s]", " ", (text or "").lower(), flags=re.UNICODE)
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def _token_overlap(a: str, b: str) -> float:
    left = set(_normalized_tokens(_normalize_seed_text(a)))
    right = set(_normalized_tokens(_normalize_seed_text(b)))
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), 1)


def _looks_like_listing_page(url: str, title: str, claim_text: str) -> bool:
    path = urlparse(url).path.lower()
    low_text = f"{title} {claim_text}".lower()
    if any(marker in low_text for marker in LISTING_PAGE_MARKERS):
        return True
    if "/search" in path or "/tag/" in path or "/category/" in path or "/archives/" in path:
        return True
    return False


def _seed_documents(claim: ClaimCandidate) -> List[RetrievedDocument]:
    scored = []
    low_claim = _normalize_seed_text(claim.normalized_text)
    for row in _load_seed_rows():
        keywords = [_normalize_seed_text(str(keyword)) for keyword in row.get("keywords", [])]
        keyword_hits = sum(1 for keyword in keywords if keyword and keyword in low_claim)
        prototype = row.get("claim", "") or row.get("text", "")
        claim_overlap = _token_overlap(claim.normalized_text, prototype)
        if not (
            claim_overlap >= 0.55
            or (claim_overlap >= 0.30 and keyword_hits >= 3)
            or keyword_hits >= 4
        ):
            continue
        profile = classify_source(row.get("url", ""))
        retrieval_score = min(1.0, (0.24 * keyword_hits) + (0.9 * claim_overlap))
        scored.append(
            (
                retrieval_score,
                RetrievedDocument(
                    query="seed_evidence",
                    url=row.get("url", "seed://local"),
                    canonical_url=row.get("url", "seed://local"),
                    title=row.get("topic", "seed evidence"),
                    snippet=row.get("text", "")[:500],
                    content=row.get("text", ""),
                    source_url=row.get("url", "seed://local"),
                    source_type=profile.source_type,
                    source_trust=profile.trust,
                    domain=profile.domain or "seed",
                    retrieval_score=retrieval_score,
                    fetch_source="seed",
                ),
            )
        )
    return [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)]


def _should_live_search_in_fast_mode(claim: ClaimCandidate) -> bool:
    text = (claim.normalized_text or "").strip()
    tokens = re.findall(r"\w+", text)
    if len(tokens) < 4 or len(tokens) > 26:
        return False
    if not text:
        return False
    lower = text.lower()
    uncertainty_markers = (
        "anonymous",
        "unverified",
        "rumor",
        "rumour",
        "no evidence",
        "no sources",
        "no reliable source",
        "no verifiable source",
        "no credible evidence",
        "cannot be verified",
        "can't be verified",
        "mixed evidence",
        "forum says",
        "social media rumor",
        "blog claims",
    )
    if any(marker in lower for marker in uncertainty_markers):
        return False
    if lower.startswith(("the claim ", "this claim ", "a claim ", "an anonymous ", "unverified channel ")):
        return False
    return bool(claim.entities or claim.dates or claim.numbers or len(tokens) >= 6)


def _filter_reason(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "unsupported_scheme"
    host = urlparse(url).netloc.lower()
    if "consent.google.com" in host or "news.google.com" in host:
        return "google_wrapper"
    profile = classify_source(url)
    if profile.source_type == "social":
        return "social_source"
    if not is_likely_article_url(url):
        return "non_article_url"
    return ""


def retrieve_documents(
    claim: ClaimCandidate,
    trace: FactCheckTrace,
    config: PipelineConfig,
    cache: SQLiteCache | None = None,
) -> List[RetrievedDocument]:
    cache = cache or get_cache()
    clean_claim_live_search = False
    prior = None
    if config.mode != "factcheck_only" and config.fast_mode:
        seeded = _seed_documents(claim)
        if seeded:
            trace.fallbacks_used.append("fast_mode_seed_first")
            return seeded[: config.max_documents]
        prior = _select_safe_prior_prediction(
            claim.normalized_text,
            probability_threshold=config.prior_probability_threshold,
            margin_threshold=config.prior_margin_threshold,
        )
        if prior is None:
            if not _should_live_search_in_fast_mode(claim):
                trace.fallbacks_used.append("fast_mode_no_live_search")
                return []
            trace.fallbacks_used.append("fast_mode_live_search_clean_claim")
            clean_claim_live_search = True
        else:
            trace.fallbacks_used.append(
                f"fast_mode_live_search_claim_prior:{prior.label}:{prior.confidence:.3f}:{prior.margin:.3f}"
            )

    queries = build_queries(claim, config)
    if config.mode != "factcheck_only" and config.fast_mode:
        queries = _select_fast_queries(
            queries,
            prior_label=prior.label if prior is not None else "",
            clean_claim_live_search=clean_claim_live_search,
        )
    trace.queries.extend(queries)

    raw_hits: List[Dict[str, str]] = []
    for query in queries:
        raw_hits.extend(search_web(query, count=config.max_search_results, cache=cache))

    seen = set()
    docs: List[RetrievedDocument] = []
    for hit in raw_hits:
        url = canonicalize_url(hit.get("url", ""))
        if url in seen:
            continue
        seen.add(url)

        reason = _filter_reason(url)
        if reason:
            trace.filtered_urls.append({"url": url, "reason": reason})
            continue

        fetch_payload = fetch_url_text(url, cache=cache)
        profile = classify_source(url)
        if config.mode == "factcheck_only" and profile.source_type != "factcheck_org":
            trace.filtered_urls.append({"url": url, "reason": "non_factcheck_source"})
            continue
        retrieval_score = _result_relevance(claim, hit.get("title", ""), hit.get("snippet", ""))
        claim_match_score = _claim_match_score(claim, fetch_payload, hit.get("title", ""), hit.get("snippet", ""))
        fetched_title = fetch_payload.get("title", "") or hit.get("title", "")
        if _looks_like_listing_page(url, fetched_title, fetch_payload.get("claim_text", "")):
            trace.filtered_urls.append({"url": url, "reason": "listing_page"})
            continue
        if config.mode == "factcheck_only" and not fetch_payload.get("is_factcheck_article"):
            trace.filtered_urls.append({"url": url, "reason": "not_factcheck_article"})
            continue
        if config.mode == "factcheck_only" and not fetch_payload.get("explicit_verdict"):
            trace.filtered_urls.append({"url": url, "reason": "no_explicit_verdict"})
            continue
        if config.mode == "factcheck_only" and claim_match_score < 0.52:
            trace.filtered_urls.append({"url": url, "reason": "low_claim_match_factcheck_only"})
            continue
        if fetch_payload.get("explicit_verdict"):
            retrieval_score = min(1.0, retrieval_score + 0.18 + 0.12 * claim_match_score)
        elif fetch_payload.get("is_factcheck_article"):
            retrieval_score = min(1.0, retrieval_score + 0.08 + 0.08 * claim_match_score)
        if claim_match_score < 0.20 and retrieval_score < 0.25:
            trace.filtered_urls.append({"url": url, "reason": "low_claim_match_generic"})
            continue
        if profile.source_type in {"major_news", "unknown"} and claim_match_score < 0.28 and retrieval_score < 0.36:
            trace.filtered_urls.append({"url": url, "reason": "low_claim_match_generic_news"})
            continue
        if fetch_payload.get("is_factcheck_article") and not fetch_payload.get("explicit_verdict") and claim_match_score < 0.50:
            trace.filtered_urls.append({"url": url, "reason": "low_claim_match_factcheck_no_verdict"})
            continue
        if fetch_payload.get("is_factcheck_article") and claim_match_score < 0.12 and retrieval_score < 0.35:
            trace.filtered_urls.append({"url": url, "reason": "low_claim_match_factcheck"})
            continue
        content = fetch_payload.get("text", "") or hit.get("snippet", "")
        if not content:
            trace.filtered_urls.append({"url": url, "reason": "empty_content"})
            continue

        docs.append(
            RetrievedDocument(
                query=hit.get("query", queries[0] if queries else claim.normalized_text),
                url=fetch_payload.get("url", url),
                canonical_url=canonicalize_url(fetch_payload.get("url", url)),
                title=fetch_payload.get("title", "") or hit.get("title", ""),
                snippet=hit.get("snippet", ""),
                content=content,
                source_url=hit.get("source_url", url) or url,
                source_type=profile.source_type,
                source_trust=profile.trust,
                domain=profile.domain,
                retrieval_score=retrieval_score,
                fetch_source=fetch_payload.get("fetch_source", "direct"),
                published_at=fetch_payload.get("published_at", "") or hit.get("published_at", ""),
                author=fetch_payload.get("author", ""),
                canonical_article_url=fetch_payload.get("canonical_article_url", "") or canonicalize_url(fetch_payload.get("url", url)),
                is_factcheck_article=bool(fetch_payload.get("is_factcheck_article", False)),
                explicit_verdict=fetch_payload.get("explicit_verdict", ""),
                explicit_verdict_label=fetch_payload.get("explicit_verdict_label", ""),
                verdict_source=fetch_payload.get("verdict_source", ""),
                claim_text=fetch_payload.get("claim_text", ""),
                ruling_text=fetch_payload.get("ruling_text", ""),
                claim_match_score=claim_match_score,
            )
        )
        if len(docs) >= config.max_documents * 2:
            break

    if not docs and config.mode != "factcheck_only":
        trace.fallbacks_used.append("seed_evidence")
        docs = _seed_documents(claim)

    docs = sorted(
        docs,
        key=lambda item: (item.retrieval_score, item.source_trust, len(item.content)),
        reverse=True,
    )
    return docs[: config.max_documents]
