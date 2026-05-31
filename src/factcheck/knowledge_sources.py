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


@dataclass(frozen=True)
class PropertySignal:
    stance: str
    reason: str
    detail: str


PROPERTY_CLASS_ALIASES: dict[str, frozenset[str]] = {
    "animal": frozenset({"animal", "animals"}),
    "mammal": frozenset({"mammal", "mammals"}),
    "bird": frozenset({"bird", "birds", "avian"}),
    "fish": frozenset({"fish", "fishes"}),
    "insect": frozenset({"insect", "insects"}),
    "arachnid": frozenset({"arachnid", "arachnids"}),
    "reptile": frozenset({"reptile", "reptiles"}),
    "amphibian": frozenset({"amphibian", "amphibians"}),
    "plant": frozenset({"plant", "plants"}),
    "fungus": frozenset({"fungus", "fungi", "fungal"}),
    "bacterium": frozenset({"bacterium", "bacteria", "bacterial"}),
    "virus": frozenset({"virus", "viruses", "viral"}),
    "disease": frozenset({"disease", "diseases", "illness"}),
    "planet": frozenset({"planet", "planets"}),
    "star": frozenset({"star", "stars"}),
    "natural satellite": frozenset({"natural satellite", "satellite", "moon"}),
    "galaxy": frozenset({"galaxy", "galaxies"}),
    "metal": frozenset({"metal", "metals", "metallic"}),
    "nonmetal": frozenset({"nonmetal", "non-metal", "nonmetals", "non-metals"}),
    "solid": frozenset({"solid", "solids"}),
    "liquid": frozenset({"liquid", "liquids"}),
    "gas": frozenset({"gas", "gases"}),
    "city": frozenset({"city", "cities", "town"}),
    "country": frozenset({"country", "countries", "nation"}),
    "continent": frozenset({"continent", "continents"}),
    "river": frozenset({"river", "rivers"}),
    "mountain": frozenset({"mountain", "mountains"}),
}

INCOMPATIBLE_CLASS_GROUPS = (
    frozenset({"mammal", "bird", "fish", "insect", "arachnid", "reptile", "amphibian", "plant", "fungus"}),
    frozenset({"planet", "star", "natural satellite", "galaxy"}),
    frozenset({"metal", "nonmetal"}),
    frozenset({"solid", "liquid", "gas"}),
    frozenset({"city", "country", "continent", "river", "mountain"}),
    frozenset({"disease", "virus", "bacterium", "fungus"}),
)

CLASS_IMPLICATIONS: dict[str, frozenset[str]] = {
    "mammal": frozenset({"animal"}),
    "bird": frozenset({"animal"}),
    "fish": frozenset({"animal"}),
    "insect": frozenset({"animal"}),
    "arachnid": frozenset({"animal"}),
    "reptile": frozenset({"animal"}),
    "amphibian": frozenset({"animal"}),
    "planet": frozenset({"astronomical object"}),
    "star": frozenset({"astronomical object"}),
    "natural satellite": frozenset({"astronomical object"}),
    "galaxy": frozenset({"astronomical object"}),
}


def _normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _token_variants(token: str) -> set[str]:
    values = {token}
    if token.endswith("ies") and len(token) > 4:
        values.add(f"{token[:-3]}y")
    elif token.endswith("y") and len(token) > 3:
        values.add(f"{token[:-1]}ies")
    if token.endswith("us") and len(token) > 3:
        values.add(f"{token[:-1]}ses")
    elif token.endswith(("s", "x", "z")) or token.endswith(("ch", "sh")):
        values.add(f"{token}es")
    elif not token.endswith("s"):
        values.add(f"{token}s")
    if token.endswith("s") and len(token) > 3:
        values.add(token[:-1])
    if token.endswith("es") and len(token) > 4:
        values.add(token[:-2])
    return values


def _phrase_variants(phrase: str) -> set[str]:
    variants = {phrase}
    tokens = phrase.split()
    if not tokens:
        return variants
    for candidate in _token_variants(tokens[-1]):
        variants.add(" ".join([*tokens[:-1], candidate]))
    return variants


def _normalized_summary_text(summary: KnowledgeSummary) -> str:
    category_text = " ".join(getattr(summary, "categories", ()))
    normalized = " " + re.sub(r"[^a-z0-9\s-]", " ", f"{summary.extract} {category_text}".lower()) + " "
    return re.sub(r"\s+", " ", normalized)


def _contains_phrase(normalized_text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_key(re.sub(r"[^a-z0-9\s-]", " ", phrase.lower()))
    return any(f" {candidate} " in normalized_text for candidate in _phrase_variants(normalized_phrase))


def _directly_negates_property(normalized_text: str, prop: str) -> bool:
    for candidate in _phrase_variants(prop):
        pattern = rf"\b(?:not|no|without)\s+(?:a\s+|an\s+|the\s+)?(?:[a-z0-9-]+\s+){{0,2}}{re.escape(candidate)}\b"
        if re.search(pattern, normalized_text):
            return True
    return False


def _property_classes(property_text: str) -> set[str]:
    prop = _normalize_key(re.sub(r"[^a-z0-9\s-]", " ", property_text.lower()))
    tokens = prop.split()
    classes: set[str] = set()
    for class_name, aliases in PROPERTY_CLASS_ALIASES.items():
        for alias in aliases:
            alias_variants = _phrase_variants(alias)
            if prop in alias_variants or (tokens and tokens[-1] in alias_variants):
                classes.add(class_name)
                break
    return classes


def _summary_classes(summary: KnowledgeSummary) -> set[str]:
    text = _normalized_summary_text(summary)
    classes: set[str] = set()
    for class_name, aliases in PROPERTY_CLASS_ALIASES.items():
        if any(_contains_phrase(text, alias) for alias in aliases):
            classes.add(class_name)
    return classes


def _classes_conflict(summary_class: str, property_class: str) -> bool:
    return any({summary_class, property_class} <= group for group in INCOMPATIBLE_CLASS_GROUPS)


def _class_supports(summary_class: str, property_class: str) -> bool:
    return summary_class == property_class or property_class in CLASS_IMPLICATIONS.get(summary_class, frozenset())


def _capital_relation_signal(summary: KnowledgeSummary, property_text: str) -> PropertySignal | None:
    prop = _normalize_key(re.sub(r"[^a-z0-9\s-]", " ", property_text.lower()))
    prop_match = re.match(r"^capital(?: city)? of (?P<place>.+)$", prop)
    if not prop_match:
        return None
    claimed_place = prop_match.group("place").strip()
    first_sentence = re.split(r"[.!?]", summary.extract, maxsplit=1)[0].lower()
    first_sentence = re.sub(r"[^a-z0-9\s-]", " ", first_sentence)
    first_sentence = re.sub(r"\s+", " ", first_sentence)
    summary_match = re.search(
        r"\bcapital(?:\s+and\s+largest\s+city|\s+city)?\s+of\s+(?:the\s+)?(?P<place>[a-z0-9 -]+?)(?:\s+with|\s+and|,|$)",
        first_sentence,
    )
    if not summary_match:
        return None
    summary_place = summary_match.group("place").strip()
    if claimed_place == summary_place or claimed_place in summary_place or summary_place in claimed_place:
        return PropertySignal(
            stance="support",
            reason=f"capital_relation_supports={claimed_place}",
            detail=f"the summary identifies {summary.title} as the capital of {summary_place}",
        )
    return PropertySignal(
        stance="refute",
        reason=f"capital_relation_refutes={claimed_place};actual={summary_place}",
        detail=f"the summary identifies {summary.title} as the capital of {summary_place}, not {claimed_place}",
    )


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
    normalized_extract = _normalized_summary_text(summary)
    if f" {prop} " in normalized_extract:
        return True

    prop_tokens = [token for token in re.findall(r"[a-z0-9]+", prop) if len(token) > 2]
    if not prop_tokens:
        return False
    extract_tokens = set(re.findall(r"[a-z0-9]+", normalized_extract))
    return all(extract_tokens & _token_variants(token) for token in prop_tokens)


def evaluate_summary_property(summary: KnowledgeSummary, property_text: str) -> PropertySignal:
    prop = _normalize_key(property_text)
    if not prop:
        return PropertySignal("unknown", "empty_property", "the property was empty")

    normalized_text = _normalized_summary_text(summary)
    capital_signal = _capital_relation_signal(summary, prop)
    if capital_signal is not None:
        return capital_signal

    if _directly_negates_property(normalized_text, prop):
        return PropertySignal(
            stance="refute",
            reason=f"wikipedia_summary_direct_negation={prop}",
            detail=f"the summary directly negates {prop}",
        )

    if summary_supports_property(summary, prop):
        return PropertySignal(
            stance="support",
            reason=f"wikipedia_summary_supports={prop}",
            detail=f"the summary contains evidence for {prop}",
        )

    property_classes = _property_classes(prop)
    if not property_classes:
        return PropertySignal("unknown", f"wikipedia_summary_no_exact_answer={prop}", f"the summary does not verify {prop}")

    classes = _summary_classes(summary)
    for property_class in sorted(property_classes):
        for summary_class in sorted(classes):
            if _class_supports(summary_class, property_class):
                return PropertySignal(
                    stance="support",
                    reason=f"taxonomy_supports={summary_class}->{property_class}",
                    detail=f"the summary classifies {summary.title} as {summary_class}, which supports {property_class}",
                )

    for property_class in sorted(property_classes):
        for summary_class in sorted(classes):
            if _classes_conflict(summary_class, property_class):
                return PropertySignal(
                    stance="refute",
                    reason=f"taxonomy_refutes={summary_class}!={property_class}",
                    detail=f"the summary classifies {summary.title} as {summary_class}, which conflicts with {property_class}",
                )

    return PropertySignal("unknown", f"wikipedia_summary_no_exact_answer={prop}", f"the summary does not verify {prop}")
