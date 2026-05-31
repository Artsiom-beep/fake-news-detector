from __future__ import annotations

try:
    from .factcheck.cache import get_cache
    from .factcheck.claims import canonicalize_claim
    from .factcheck.config import build_config
    from .factcheck.ingest import fetch_url_text, is_likely_article_url
    from .factcheck.retrieval import retrieve_documents, search_web
    from .factcheck.schemas import ClaimCandidate, FactCheckTrace
except ImportError:
    from factcheck.cache import get_cache
    from factcheck.claims import canonicalize_claim
    from factcheck.config import build_config
    from factcheck.ingest import fetch_url_text, is_likely_article_url
    from factcheck.retrieval import retrieve_documents, search_web
    from factcheck.schemas import ClaimCandidate, FactCheckTrace


def web_search_brave(query: str, count: int = 5):
    return search_web(query, count=count, cache=get_cache())


def retrieve_evidence(claim: str, top_k: int = 5):
    config = build_config(fast_mode=False)
    trace = FactCheckTrace()
    candidate = ClaimCandidate(
        raw_text=claim,
        normalized_text=canonicalize_claim(claim),
        score=1.0,
    )
    docs = retrieve_documents(candidate, trace=trace, config=config, cache=get_cache())
    out = []
    for doc in docs[:top_k]:
        out.append(
            {
                "title": doc.title,
                "url": doc.url,
                "source_url": doc.source_url,
                "snippet": doc.snippet,
                "content": doc.content,
                "source_type": doc.source_type,
                "source_trust": doc.source_trust,
                "retrieval_relevance": doc.retrieval_score,
            }
        )
    return out
