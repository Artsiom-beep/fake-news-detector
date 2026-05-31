from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

import requests

from .cache import SQLiteCache, get_cache

WIKIPEDIA_SUMMARY_NAMESPACE = "wikipedia_summary_v2"
WIKIPEDIA_OPENSEARCH_NAMESPACE = "wikipedia_opensearch_v1"
WIKIPEDIA_CATEGORIES_NAMESPACE = "wikipedia_categories_v1"
USER_AGENT = "fake-news-detector-local-demo/1.0 (source-backed knowledge lookup)"


@dataclass(frozen=True)
class KnowledgeSummary:
    title: str
    extract: str
    url: str
    source: str = "wikipedia_summary_v2"
    categories: tuple[str, ...] = ()


def _normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _summary_from_payload(payload: dict) -> KnowledgeSummary | None:
    if not payload or payload.get("type") == "disambiguation":
        return None
    extract = (payload.get("extract") or "").strip()
    title = (payload.get("title") or "").strip()
    url = (
        ((payload.get("content_urls") or {}).get("desktop") or {}).get("page")
        or payload.get("url")
        or ""
    )
    if len(extract) < 40 or not title or not url:
        return None
    return KnowledgeSummary(title=title, extract=extract, url=url)


def _fetch_summary_by_title(title: str) -> KnowledgeSummary | None:
    response = requests.get(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'))}",
        timeout=6,
        headers={"User-Agent": USER_AGENT},
    )
    if response.status_code != 200:
        return None
    return _summary_from_payload(response.json())


def _fetch_categories(title: str, cache: SQLiteCache) -> tuple[str, ...]:
    key = _normalize_key(title)
    cached = cache.get(WIKIPEDIA_CATEGORIES_NAMESPACE, key)
    if isinstance(cached, list):
        return tuple(str(item) for item in cached)
    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "categories",
                "titles": title,
                "cllimit": 50,
                "format": "json",
            },
            timeout=6,
            headers={"User-Agent": USER_AGENT},
        )
        if response.status_code != 200:
            cache.set(WIKIPEDIA_CATEGORIES_NAMESPACE, key, [])
            return ()
        pages = ((response.json().get("query") or {}).get("pages") or {}).values()
        categories: list[str] = []
        for page in pages:
            for item in page.get("categories", []):
                category = re.sub(r"^Category:", "", item.get("title", ""))
                if category:
                    categories.append(category)
        cache.set(WIKIPEDIA_CATEGORIES_NAMESPACE, key, categories)
        return tuple(categories)
    except Exception:
        cache.set(WIKIPEDIA_CATEGORIES_NAMESPACE, key, [])
        return ()


def _search_wikipedia_title(query: str, cache: SQLiteCache) -> str:
    key = _normalize_key(query)
    cached = cache.get(WIKIPEDIA_OPENSEARCH_NAMESPACE, key)
    if isinstance(cached, str):
        return cached
    try:
        response = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "opensearch",
                "search": query,
                "limit": 1,
                "namespace": 0,
                "format": "json",
            },
            timeout=6,
            headers={"User-Agent": USER_AGENT},
        )
        if response.status_code != 200:
            cache.set(WIKIPEDIA_OPENSEARCH_NAMESPACE, key, "")
            return ""
        payload = response.json()
        title = payload[1][0] if isinstance(payload, list) and len(payload) > 1 and payload[1] else ""
        cache.set(WIKIPEDIA_OPENSEARCH_NAMESPACE, key, title)
        return title
    except Exception:
        cache.set(WIKIPEDIA_OPENSEARCH_NAMESPACE, key, "")
        return ""


def fetch_wikipedia_summary(subject: str, cache: SQLiteCache | None = None) -> KnowledgeSummary | None:
    cache = cache or get_cache()
    key = _normalize_key(subject)
    if not key:
        return None
    cached = cache.get(WIKIPEDIA_SUMMARY_NAMESPACE, key)
    if isinstance(cached, dict):
        return KnowledgeSummary(
            title=cached.get("title", ""),
            extract=cached.get("extract", ""),
            url=cached.get("url", ""),
            source=cached.get("source", "wikipedia_summary_v2"),
            categories=tuple(cached.get("categories", ())),
        ) if cached.get("extract") else None

    summary = None
    try:
        summary = _fetch_summary_by_title(subject)
        if summary is None:
            title = _search_wikipedia_title(subject, cache)
            summary = _fetch_summary_by_title(title) if title else None
        if summary is not None:
            summary = KnowledgeSummary(
                title=summary.title,
                extract=summary.extract,
                url=summary.url,
                source=summary.source,
                categories=_fetch_categories(summary.title, cache),
            )
    except Exception:
        summary = None

    cache.set(
        WIKIPEDIA_SUMMARY_NAMESPACE,
        key,
        {
            "title": summary.title,
            "extract": summary.extract,
            "url": summary.url,
            "source": summary.source,
            "categories": list(summary.categories),
        }
        if summary
        else {},
    )
    return summary


def summary_supports_property(summary: KnowledgeSummary, property_text: str) -> bool:
    prop = _normalize_key(property_text)
    if not prop:
        return False
    category_text = " ".join(getattr(summary, "categories", ()))
    normalized_extract = " " + re.sub(r"[^a-z0-9\s-]", " ", f"{summary.extract} {category_text}".lower()) + " "
    normalized_extract = re.sub(r"\s+", " ", normalized_extract)
    if f" {prop} " in normalized_extract:
        return True

    prop_tokens = [token for token in re.findall(r"[a-z0-9]+", prop) if len(token) > 2]
    if not prop_tokens:
        return False
    extract_tokens = set(re.findall(r"[a-z0-9]+", normalized_extract))

    def variants(token: str) -> set[str]:
        values = {token}
        if token.endswith("ies") and len(token) > 4:
            values.add(f"{token[:-3]}y")
        elif token.endswith("y") and len(token) > 3:
            values.add(f"{token[:-1]}ies")
        if token.endswith("s") and len(token) > 3:
            values.add(token[:-1])
        else:
            values.add(f"{token}s")
        return values

    return all(extract_tokens & variants(token) for token in prop_tokens)
