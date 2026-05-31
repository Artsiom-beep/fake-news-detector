from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse
import json

from bs4 import BeautifulSoup, Tag

from .source_registry import classify_source


def _clean_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("\u00a0", " ")
    normalized = re.sub(r"[\t\r\f\v]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _token_overlap(a: str, b: str) -> float:
    left = set(re.findall(r"\w+", (a or "").lower()))
    right = set(re.findall(r"\w+", (b or "").lower()))
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), 1)


def _get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "").strip()
    except Exception:
        return ""


def _join_chunks(chunks: list[str], max_len: int = 40000) -> str:
    text = _clean_text(" ".join(chunk for chunk in chunks if _clean_text(chunk)))
    return text[:max_len]


def _extract_generic_article_text(soup: BeautifulSoup, max_len: int = 40000) -> tuple[str, str]:
    title = _clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    article = soup.find("article")
    if article is not None:
        chunks = [node.get_text(" ", strip=True) for node in article.find_all(["h1", "h2", "p", "li"])]
    else:
        chunks = [node.get_text(" ", strip=True) for node in soup.find_all(["h1", "h2", "p"])]

    text = _join_chunks(chunks, max_len=max_len)
    if len(text) < 400:
        text = _clean_text(soup.get_text(" ", strip=True))[:max_len]
    return title, text


def _meta_value(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        selector = (
            soup.find("meta", attrs={"property": name})
            or soup.find("meta", attrs={"name": name})
            or soup.find("meta", attrs={"itemprop": name})
        )
        if selector and selector.get("content"):
            return _clean_text(selector.get("content", ""))
    return ""


def _extract_jsonld_metadata(soup: BeautifulSoup) -> dict:
    metadata = {"published_at": "", "author": "", "canonical_url": ""}
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(node.string or "")
        except Exception:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                candidates.extend(entry for entry in graph if isinstance(entry, dict))
            item_type = item.get("@type", "")
            if isinstance(item_type, list):
                item_type = " ".join(str(value) for value in item_type)
            if not any(marker in str(item_type).lower() for marker in ("article", "newsarticle", "reportage")):
                continue
            metadata["published_at"] = metadata["published_at"] or _clean_text(
                item.get("datePublished") or item.get("dateCreated") or item.get("dateModified") or ""
            )
            author = item.get("author") or item.get("creator")
            if isinstance(author, dict):
                metadata["author"] = metadata["author"] or _clean_text(author.get("name", ""))
            elif isinstance(author, list):
                names = [entry.get("name", "") if isinstance(entry, dict) else str(entry) for entry in author]
                metadata["author"] = metadata["author"] or _clean_text(", ".join(name for name in names if name))
            elif author:
                metadata["author"] = metadata["author"] or _clean_text(str(author))
            page_ref = item.get("url") or item.get("mainEntityOfPage", "")
            if isinstance(page_ref, dict):
                page_ref = page_ref.get("@id") or page_ref.get("url") or ""
            metadata["canonical_url"] = metadata["canonical_url"] or _clean_text(str(page_ref))
    return metadata


def _extract_metadata(url: str, soup: BeautifulSoup) -> dict:
    canonical = ""
    canonical_node = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical_node and canonical_node.get("href"):
        canonical = _clean_text(canonical_node.get("href", ""))
    jsonld = _extract_jsonld_metadata(soup)
    return {
        "published_at": (
            _meta_value(soup, "article:published_time", "datePublished", "pubdate", "date")
            or jsonld.get("published_at", "")
        ),
        "author": (
            _meta_value(soup, "author", "article:author", "byl")
            or jsonld.get("author", "")
        ),
        "canonical_url": canonical or jsonld.get("canonical_url", "") or url,
    }


def _map_verdict_label(raw_label: str) -> tuple[str, str]:
    low = _clean_text(raw_label).lower()
    if not low:
        return "", ""

    high_priority_map = [
        ("not true", "refute"),
        ("did not", "refute"),
        ("didn't", "refute"),
        ("does not", "refute"),
        ("doesn't", "refute"),
        ("is not", "refute"),
        ("isn't", "refute"),
        ("are not", "refute"),
        ("aren't", "refute"),
        ("fabrication", "refute"),
        ("fabricated", "refute"),
        ("falsely implied", "refute"),
        ("misrepresented", "refute"),
        ("peddled as", "refute"),
        ("satire", "refute"),
        ("satirical", "refute"),
        ("misattributed", "refute"),
        ("unrelated", "refute"),
        ("old video", "refute"),
        ("no, ", "refute"),
        ("this is correct", "support"),
        ("this is true", "support"),
    ]
    for marker, label in high_priority_map:
        if marker in low:
            return label, marker

    explicit_map = [
        ("pants on fire", "refute"),
        ("mostly false", "refute"),
        ("false", "refute"),
        ("fake", "refute"),
        ("hoax", "refute"),
        ("misleading", "refute"),
        ("incorrect", "refute"),
        ("debunked", "refute"),
        ("unsupported", "refute"),
        ("out of context", "uncertain"),
        ("missing context", "uncertain"),
        ("not enough evidence", "uncertain"),
        ("mixed", "uncertain"),
        ("conflicting evidence", "uncertain"),
        ("half true", "uncertain"),
        ("partly false", "uncertain"),
        ("partly true", "uncertain"),
        ("mostly true", "support"),
        ("true", "support"),
        ("correct", "support"),
        ("accurate", "support"),
        ("supported", "support"),
        ("authentic", "support"),
    ]
    for marker, label in explicit_map:
        if marker in low:
            return label, marker
    return "", ""


def _extract_verdict_from_text(text: str) -> tuple[str, str]:
    cleaned = _clean_text(text).lower()
    if not cleaned:
        return "", ""

    patterns = [
        r"\bverdict\s*:\s*(pants on fire|mostly false|false|half true|mostly true|true|misleading|fake)\b",
        r"\bwe rate (?:this|the claim|the statement|it|his claim|her claim)?[^.]{0,120}?(pants on fire|mostly false|false|half true|mostly true|true)\b",
        r"\bour verdict[^.]{0,200}?(pants on fire|mostly false|false|half true|mostly true|true)\b",
        r"\bverdict[^.]{0,200}?(misleading|fake|false|true|mostly false|mostly true|half true|missing context|out of context)\b",
        r"\bthis claim (?:is|was) (false|true|misleading|incorrect|unsupported)\b",
        r"\bclaim (?:is|was) (false|true|misleading|incorrect|unsupported)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.I)
        if match:
            label, normalized = _map_verdict_label(match.group(1))
            if label:
                return label, normalized

    refute_patterns = [
        r"\bclaiming to show\b.{0,220}\bis from\b",
        r"\bclaimed to show\b.{0,220}\bis from\b",
        r"\bpurportedly showing\b.{0,220}\bis unrelated\b",
        r"\bpurportedly shows\b.{0,220}\bis unrelated\b",
    ]
    for pattern in refute_patterns:
        if re.search(pattern, cleaned, flags=re.I):
            return "refute", "misrepresented"

    if cleaned.startswith("no, ") or cleaned.startswith("no "):
        return "refute", "no"
    return _map_verdict_label(cleaned)


def _extract_heading_following_text(node: Tag | None, max_paragraphs: int = 3) -> str:
    if node is None:
        return ""

    collected: list[str] = []
    current = node
    while current is not None and len(collected) < max_paragraphs:
        current = current.find_next_sibling()
        if current is None:
            break
        if getattr(current, "name", "") in {"h1", "h2", "h3", "h4", "strong"}:
            break
        text = _clean_text(current.get_text(" ", strip=True))
        if len(text) >= 40:
            collected.append(text)
    return _join_chunks(collected, max_len=2500)


def _parse_politifact(url: str, soup: BeautifulSoup) -> dict:
    title, fallback_text = _extract_generic_article_text(soup)
    claim_node = soup.select_one(".m-statement__quote")
    claim_text = _clean_text(claim_node.get_text(" ", strip=True) if claim_node else "")

    ruling_anchor = soup.find(
        lambda node: isinstance(node, Tag)
        and node.name in {"strong", "h2", "h3", "h4"}
        and "our ruling" in _clean_text(node.get_text(" ", strip=True)).lower()
    )
    ruling_text = _extract_heading_following_text(ruling_anchor, max_paragraphs=3)
    if not ruling_text:
        text = _clean_text(soup.get_text(" ", strip=True))
        match = re.search(r"Our ruling(.{80,1200})", text, flags=re.I)
        if match:
            ruling_text = _clean_text(match.group(1))

    verdict, verdict_label = _extract_verdict_from_text(ruling_text or title)
    structured_chunks = [claim_text, ruling_text]
    text = _join_chunks(structured_chunks, max_len=4000) or fallback_text
    return {
        "title": title,
        "text": text,
        "claim_text": claim_text,
        "ruling_text": ruling_text,
        "explicit_verdict": verdict,
        "explicit_verdict_label": verdict_label,
        "verdict_source": "politifact_ruling" if ruling_text else "",
        "is_factcheck_article": True,
    }


def _parse_fullfact(url: str, soup: BeautifulSoup) -> dict:
    title, fallback_text = _extract_generic_article_text(soup)
    claim_text = ""
    ruling_text = ""

    card_titles = [_clean_text(node.get_text(" ", strip=True)).lower() for node in soup.select(".card-title")]
    card_texts = [_clean_text(node.get_text(" ", strip=True)) for node in soup.select(".card-text")]
    if "what was claimed" in card_titles and card_texts:
        claim_index = card_titles.index("what was claimed")
        if claim_index < len(card_texts):
            claim_text = card_texts[claim_index]
    if "our verdict" in card_titles and card_texts:
        verdict_index = card_titles.index("our verdict")
        if verdict_index < len(card_texts):
            ruling_text = card_texts[verdict_index]

    if not claim_text or not ruling_text:
        article_text = _clean_text(
            (soup.find("article").get_text(" ", strip=True) if soup.find("article") else soup.get_text(" ", strip=True))
        )
        match = re.search(
            r"What was claimed\s+(.*?)\s+Our verdict\s+(.*?)(?:Join \d|Sign up|Read more|$)",
            article_text,
            flags=re.I,
        )
        if match:
            claim_text = claim_text or _clean_text(match.group(1))
            ruling_text = ruling_text or _clean_text(match.group(2))

    verdict, verdict_label = _extract_verdict_from_text(f"{title}. {ruling_text}")
    text = _join_chunks([claim_text, ruling_text], max_len=4000) or fallback_text
    return {
        "title": title,
        "text": text,
        "claim_text": claim_text or title,
        "ruling_text": ruling_text,
        "explicit_verdict": verdict,
        "explicit_verdict_label": verdict_label,
        "verdict_source": "fullfact_claim_review" if verdict else "",
        "is_factcheck_article": True,
    }


def _parse_generic_factcheck(url: str, soup: BeautifulSoup) -> dict:
    title, fallback_text = _extract_generic_article_text(soup)
    heading = _clean_text(
        (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "") or title
    )
    ruling_anchor = soup.find(
        lambda node: isinstance(node, Tag)
        and node.name in {"strong", "h2", "h3", "h4"}
        and any(
            marker in _clean_text(node.get_text(" ", strip=True)).lower()
            for marker in {"our verdict", "verdict", "the facts", "fact check", "bottom line", "what we found"}
        )
    )
    ruling_text = _extract_heading_following_text(ruling_anchor, max_paragraphs=4)
    if not ruling_text:
        article = soup.find("article")
        paragraph_source = article if article is not None else soup
        chunks = []
        for paragraph in paragraph_source.find_all(["p", "li"]):
            text = _clean_text(paragraph.get_text(" ", strip=True))
            if len(text) < 40:
                continue
            chunks.append(text)
            if len(chunks) >= 3:
                break
        ruling_text = _join_chunks(chunks, max_len=2500)
    if not ruling_text:
        article_text = _clean_text((soup.find("article").get_text(" ", strip=True) if soup.find("article") else soup.get_text(" ", strip=True)))
        match = re.search(
            r"(our verdict|verdict:|fact check:)(.{40,1200})",
            article_text,
            flags=re.I,
        )
        if match:
            ruling_text = _clean_text(match.group(0))

    verdict, verdict_label = _extract_verdict_from_text(f"{title}. {ruling_text}")
    if not verdict and heading.lower().startswith("no,"):
        verdict, verdict_label = "refute", "no"
    structured_chunks = [heading, ruling_text]
    text = _join_chunks(structured_chunks, max_len=4000) or fallback_text
    return {
        "title": title,
        "text": text,
        "claim_text": heading,
        "ruling_text": ruling_text,
        "explicit_verdict": verdict,
        "explicit_verdict_label": verdict_label,
        "verdict_source": "generic_factcheck" if verdict else "",
        "is_factcheck_article": True,
    }


def parse_text_fallback(url: str, title: str, text: str) -> dict:
    profile = classify_source(url)
    looks_like_factcheck = (
        profile.source_type == "factcheck_org"
        or "fact check" in (title or "").lower()
        or any(marker in (url or "").lower() for marker in ("factcheck", "fact-check", "/factchecks/"))
    )
    cleaned_title = _clean_text(title)
    cleaned_text = _clean_text(text)
    verdict = ""
    verdict_label = ""
    if looks_like_factcheck:
        verdict, verdict_label = _extract_verdict_from_text(f"{cleaned_title}. {cleaned_text[:2500]}")
    return {
        "title": cleaned_title,
        "text": cleaned_text,
        "claim_text": cleaned_title,
        "ruling_text": cleaned_text[:2500] if verdict else "",
        "explicit_verdict": verdict,
        "explicit_verdict_label": verdict_label,
        "verdict_source": "text_fallback_factcheck" if verdict else "",
        "is_factcheck_article": looks_like_factcheck,
    }


def parse_page(url: str, html: str, max_len: int = 40000) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    domain = _get_domain(url)
    title, text = _extract_generic_article_text(soup, max_len=max_len)
    profile = classify_source(url)
    looks_like_factcheck = (
        profile.source_type == "factcheck_org"
        or "fact check" in title.lower()
        or any(marker in url.lower() for marker in ("factcheck", "fact-check", "/factchecks/"))
    )

    parsed = {
        "title": title,
        "text": text,
        "claim_text": "",
        "ruling_text": "",
        "explicit_verdict": "",
        "explicit_verdict_label": "",
        "verdict_source": "",
        "is_factcheck_article": False,
        **_extract_metadata(url, soup),
    }

    if domain.endswith("politifact.com"):
        parsed = {**_parse_politifact(url, soup), **_extract_metadata(url, soup)}
    elif domain.endswith("fullfact.org"):
        parsed = {**_parse_fullfact(url, soup), **_extract_metadata(url, soup)}
    elif looks_like_factcheck:
        parsed = {**_parse_generic_factcheck(url, soup), **_extract_metadata(url, soup)}

    return parsed
