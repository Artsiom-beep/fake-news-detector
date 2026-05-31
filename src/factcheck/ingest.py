from __future__ import annotations

import re
import unicodedata
from typing import Dict
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .cache import SQLiteCache, get_cache
from .domain_parsers import parse_page, parse_text_fallback

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "gclid",
    "fbclid",
    "ved",
    "ref",
    "ref_src",
}
FETCH_CACHE_VERSION = "fetch_v5"


def canonicalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("\u00a0", " ")
    normalized = re.sub(r"[\t\r\f\v]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def canonicalize_url(url: str) -> str:
    try:
        parsed = urlparse((url or "").strip())
        query_items = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if k.lower() not in TRACKING_PARAMS
        ]
        normalized = parsed._replace(
            scheme=(parsed.scheme or "https").lower(),
            netloc=parsed.netloc.lower(),
            query=urlencode(query_items),
            fragment="",
        )
        cleaned = urlunparse(normalized)
        return cleaned.rstrip("/")
    except Exception:
        return (url or "").strip()


def is_likely_article_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        path = parsed.path.strip("/")
        host = parsed.netloc.lower().replace("www.", "")
        if host == "factcheck.afp.com" and path.startswith("doc.afp.com."):
            return True
        if not path:
            return False
        segments = [segment for segment in path.split("/") if segment]
        if len(segments) <= 1:
            return False
        lower_segments = [segment.lower() for segment in segments]
        if any(segment in {"search", "mt-search", "cgi-bin"} for segment in lower_segments):
            return False
        if any(segment.endswith(".fcgi") for segment in lower_segments):
            return False
        tail = segments[-1].lower()
        if tail in {
            "news",
            "world",
            "politics",
            "technology",
            "business",
            "science",
            "video",
            "videos",
            "live",
            "topics",
            "topic",
            "category",
            "categories",
            "tag",
        }:
            return False
        if re.search(r"\d{4}/\d{2}/\d{2}", path):
            return True
        if len(tail.split("-")) >= 4:
            return True
        if len(segments) >= 3:
            return True
        return False
    except Exception:
        return False


def _extract_text_from_html(url: str, html: str, max_len: int = 40000) -> Dict[str, str]:
    parsed = parse_page(url=url, html=html, max_len=max_len)
    return {
        "title": canonicalize_text(parsed.get("title", "")),
        "text": canonicalize_text(parsed.get("text", ""))[:max_len],
        "claim_text": canonicalize_text(parsed.get("claim_text", "")),
        "ruling_text": canonicalize_text(parsed.get("ruling_text", "")),
        "explicit_verdict": canonicalize_text(parsed.get("explicit_verdict", "")),
        "explicit_verdict_label": canonicalize_text(parsed.get("explicit_verdict_label", "")),
        "verdict_source": canonicalize_text(parsed.get("verdict_source", "")),
        "is_factcheck_article": bool(parsed.get("is_factcheck_article", False)),
        "published_at": canonicalize_text(parsed.get("published_at", "")),
        "author": canonicalize_text(parsed.get("author", "")),
        "canonical_article_url": canonicalize_url(parsed.get("canonical_url", "") or url),
    }


def _title_from_url_slug(url: str) -> str:
    try:
        path = urlparse(url or "").path.strip("/")
        tail = path.split("/")[-1] if path else ""
        if not tail:
            return ""
        tail = re.sub(r"\.(html?|amp)$", "", tail, flags=re.IGNORECASE)
        tail = re.sub(r"\b\d{4}[-_]\d{2}[-_]\d{2}\b", "", tail)
        tail = re.sub(r"[-_]+", " ", tail)
        return canonicalize_text(tail)
    except Exception:
        return ""


def _factcheck_fallback_payload(url: str, title: str, text: str, fetch_source: str) -> Dict[str, str]:
    parsed = parse_text_fallback(url, title or _title_from_url_slug(url), text)
    return {
        "text": canonicalize_text(parsed.get("text", ""))[:40000],
        "title": canonicalize_text(parsed.get("title", "")),
        "url": url,
        "fetch_source": fetch_source,
        "claim_text": canonicalize_text(parsed.get("claim_text", "")),
        "ruling_text": canonicalize_text(parsed.get("ruling_text", "")),
        "explicit_verdict": canonicalize_text(parsed.get("explicit_verdict", "")),
        "explicit_verdict_label": canonicalize_text(parsed.get("explicit_verdict_label", "")),
        "verdict_source": canonicalize_text(parsed.get("verdict_source", "")),
        "is_factcheck_article": bool(parsed.get("is_factcheck_article", False)),
        "published_at": "",
        "author": "",
        "canonical_article_url": url,
    }


def _fetch_via_jina(url: str, timeout: int = 20) -> Dict[str, str]:
    try:
        normalized = url.replace("https://", "").replace("http://", "")
        mirror = f"https://r.jina.ai/http://{normalized}"
        response = requests.get(mirror, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 200 and response.text:
            text = canonicalize_text(response.text)[:40000]
            title_match = re.search(r"\bTitle:\s*(.+?)\s+URL Source:", text)
            published_match = re.search(r"\bPublished Time:\s*([^\s]+)", text)
            title = canonicalize_text(title_match.group(1)) if title_match else ""
            published_at = canonicalize_text(published_match.group(1)) if published_match else ""
            fallback = _factcheck_fallback_payload(url, title, text, "jina")
            return {
                "text": text,
                "title": (fallback["title"] or title) if title.lower() not in {"access denied", "just a moment"} else "",
                "url": url,
                "fetch_source": "jina",
                "claim_text": fallback["claim_text"],
                "ruling_text": fallback["ruling_text"],
                "explicit_verdict": fallback["explicit_verdict"],
                "explicit_verdict_label": fallback["explicit_verdict_label"],
                "verdict_source": fallback["verdict_source"],
                "is_factcheck_article": fallback["is_factcheck_article"],
                "published_at": published_at,
                "author": "",
                "canonical_article_url": url,
            }
    except Exception:
        pass
    fallback = _factcheck_fallback_payload(url, "", "", "jina")
    return {
        "text": "",
        "title": fallback["title"],
        "url": url,
        "fetch_source": "jina",
        "claim_text": fallback["claim_text"],
        "ruling_text": fallback["ruling_text"],
        "explicit_verdict": fallback["explicit_verdict"],
        "explicit_verdict_label": fallback["explicit_verdict_label"],
        "verdict_source": fallback["verdict_source"],
        "is_factcheck_article": fallback["is_factcheck_article"],
        "published_at": "",
        "author": "",
        "canonical_article_url": url,
    }


def fetch_url_text(
    url: str,
    timeout: int = 15,
    cache: SQLiteCache | None = None,
) -> Dict[str, str]:
    cache = cache or get_cache()
    canonical_url = canonicalize_url(url)
    cache_key = f"{FETCH_CACHE_VERSION}:{canonical_url}"
    cached = cache.get("fetch", cache_key)
    if cached is not None:
        return cached

    payload = {
        "text": "",
        "title": "",
        "url": canonical_url,
        "fetch_source": "direct",
        "claim_text": "",
        "ruling_text": "",
        "explicit_verdict": "",
        "explicit_verdict_label": "",
        "verdict_source": "",
        "is_factcheck_article": False,
        "published_at": "",
        "author": "",
        "canonical_article_url": canonical_url,
    }
    try:
        response = requests.get(
            canonical_url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if response.status_code == 200 and response.text:
            final_url = canonicalize_url(getattr(response, "url", canonical_url) or canonical_url)
            extracted = _extract_text_from_html(final_url, response.text)
            payload = {
                "text": extracted["text"],
                "title": extracted["title"],
                "url": final_url,
                "fetch_source": "direct",
                "claim_text": extracted.get("claim_text", ""),
                "ruling_text": extracted.get("ruling_text", ""),
                "explicit_verdict": extracted.get("explicit_verdict", ""),
                "explicit_verdict_label": extracted.get("explicit_verdict_label", ""),
                "verdict_source": extracted.get("verdict_source", ""),
                "is_factcheck_article": bool(extracted.get("is_factcheck_article", False)),
                "published_at": extracted.get("published_at", ""),
                "author": extracted.get("author", ""),
                "canonical_article_url": extracted.get("canonical_article_url", final_url),
            }
    except Exception:
        payload = {
            "text": "",
            "title": "",
            "url": canonical_url,
            "fetch_source": "direct",
            "claim_text": "",
            "ruling_text": "",
            "explicit_verdict": "",
            "explicit_verdict_label": "",
            "verdict_source": "",
            "is_factcheck_article": False,
            "published_at": "",
            "author": "",
            "canonical_article_url": canonical_url,
        }

    if not payload["text"]:
        payload = _fetch_via_jina(canonical_url)

    cache.set("fetch", cache_key, payload)
    return payload
