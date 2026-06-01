from __future__ import annotations

import re
from typing import List

from .schemas import ClaimCandidate

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
ENTITY_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b")
DATE_PATTERN = re.compile(r"\b(?:19|20)\d{2}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}(?:,\s+\d{4})?\b", re.I)
NUMBER_PATTERN = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")
NUMERIC_COMPARISON_PATTERN = re.compile(r"^\s*-?\d+(?:[.,]\d+)?\s*(?:>=|<=|==|>|<|=)\s*-?\d+(?:[.,]\d+)?\s*$")
FACT_HINTS = [
    r"\b(said|announced|reported|stated|confirmed|denied|claims?|tested|found|showed|falsely|misleading|debunked)\b",
    r"\b(according to|fact check|fact-check|claim|verdict)\b",
]
SHORT_FACT_VERBS = {
    "is",
    "are",
    "was",
    "were",
    "has",
    "have",
    "had",
    "will",
    "can",
    "could",
    "does",
    "do",
    "did",
    "equal",
    "equals",
    "cause",
    "causes",
    "cure",
    "cures",
    "include",
    "includes",
    "live",
    "lives",
    "orbit",
    "orbits",
    "prevent",
    "prevents",
    "treat",
    "treats",
}
LOW_SPECIFICITY_META_PATTERNS = [
    re.compile(r"\b(the\s+)?claim\s+(has|had|contains|cites)?\s*no\s+reliable\s+(source|sources|evidence)\b", re.I),
    re.compile(r"\b(no|without)\s+reliable\s+(source|sources|evidence)\b", re.I),
    re.compile(r"\bcannot\s+be\s+(independently\s+)?verified\b", re.I),
    re.compile(r"\b(unverified|unsourced)\s+(claim|post|story|report)\b", re.I),
]
GENERIC_INITIAL_ENTITY_WORDS = {
    "A",
    "All",
    "An",
    "Because",
    "Due",
    "Even",
    "More",
    "Remember",
    "Says",
    "Speaking",
    "The",
    "This",
    "Those",
    "They",
    "Video",
    "Wearing",
    "Why",
}


def _normalize_abbreviations(text: str) -> str:
    return re.sub(r"\b(?:[A-Za-z]\.){2,}", lambda match: match.group(0).replace(".", ""), text or "")


def canonicalize_claim(claim: str) -> str:
    claim = _normalize_abbreviations(claim).strip()
    claim = re.sub(r"\s+", " ", claim)
    claim = re.sub(
        r"\b(according to|reportedly|it is claimed that|quick triage note|claim under review|before sharing|sanity-check this statement)\b[:\-]?",
        "",
        claim,
        flags=re.I,
    )
    return claim.strip(" .:-\"'")


def _extract_entities(text: str) -> List[str]:
    entities = ENTITY_PATTERN.findall(text or "")
    cleaned: List[str] = []
    for entity in entities:
        if " " not in entity and entity in GENERIC_INITIAL_ENTITY_WORDS:
            continue
        cleaned.append(entity)
    return cleaned


def is_low_specificity_meta_claim(claim: ClaimCandidate) -> bool:
    meaningful_numbers = [number for number in claim.numbers if number not in {"19"}]
    if claim.entities or claim.dates or meaningful_numbers:
        return False
    text = claim.normalized_text or claim.raw_text or ""
    return any(pattern.search(text) for pattern in LOW_SPECIFICITY_META_PATTERNS)


def _looks_like_short_claim(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned or cleaned.endswith("?"):
        return False
    if NUMERIC_COMPARISON_PATTERN.match(cleaned):
        return True
    tokens = re.findall(r"[A-Za-z0-9]+", cleaned.lower())
    if len(tokens) < 3 or len(tokens) > 14:
        return False
    if tokens[0] in {"who", "what", "where", "when", "why", "how"}:
        return False
    return bool(set(tokens) & SHORT_FACT_VERBS)


def _score_claim(text: str) -> float:
    score = 0.0
    low = text.lower()
    if _looks_like_short_claim(text):
        score += 0.55
    if 35 <= len(text) <= 260:
        score += 1.0
    if _extract_entities(text):
        score += 1.0
    if DATE_PATTERN.search(text):
        score += 1.0
    if NUMBER_PATTERN.search(text):
        score += 0.75
    for pattern in FACT_HINTS:
        if re.search(pattern, low):
            score += 0.8
    if any(word in low for word in ["maybe", "might", "opinion", "feel"]):
        score -= 0.6
    return score


def _split_sentences(text: str) -> List[str]:
    sentences = []
    protected_text = _normalize_abbreviations(text)
    for chunk in SENTENCE_SPLIT.split((protected_text or "").strip()):
        cleaned = re.sub(r"\s+", " ", chunk).strip()
        if len(cleaned) >= 25 or _looks_like_short_claim(cleaned):
            sentences.append(cleaned)
    return sentences


def _split_atomic(sentence: str) -> List[str]:
    parts = re.split(r"\s*(?:;|\s+and\s+|\s+but\s+|\s+however\s+)\s*", sentence, flags=re.I)
    cleaned_parts = [part.strip(" ,.-") for part in parts if len(part.strip(" ,.-")) >= 25]
    if len(cleaned_parts) <= 1:
        return cleaned_parts or [sentence]
    return [sentence.strip(" ,.-")] + cleaned_parts


def _extract_factcheck_blocks(text: str) -> List[str]:
    patterns = [
        re.compile(
            r"(?:^|\n)\s*(?:claim|viral claim)\s*[:\-]\s*(?P<claim>.{20,500}?)(?=\n\s*(?:fact|verdict|fact check|fact-check)\s*[:\-])",
            flags=re.I | re.S,
        ),
        re.compile(
            r"(?:^|\n)\s*(?:fact|verdict|fact check|fact-check)\s*[:\-]\s*(?P<fact>.{20,500}?)(?=\n\s*\n|\Z)",
            flags=re.I | re.S,
        ),
    ]
    blocks: List[str] = []
    for pattern in patterns:
        for match in pattern.finditer(text or ""):
            key = "claim" if "claim" in match.groupdict() else "fact"
            blocks.append(re.sub(r"\s+", " ", match.group(key)).strip(" .:-"))
    return blocks


def extract_claims(text: str, max_claims: int = 4) -> List[ClaimCandidate]:
    candidates: List[ClaimCandidate] = []
    sentences = _split_sentences(text)

    for block in _extract_factcheck_blocks(text):
        normalized = canonicalize_claim(block)
        if normalized:
            candidates.append(
                ClaimCandidate(
                    raw_text=block,
                    normalized_text=normalized,
                    score=_score_claim(normalized) + 0.8,
                    entities=_extract_entities(normalized),
                    dates=DATE_PATTERN.findall(normalized),
                    numbers=NUMBER_PATTERN.findall(normalized),
                    source="factcheck_block",
                )
            )

    for index, sentence in enumerate(sentences):
        for part in _split_atomic(sentence):
            normalized = canonicalize_claim(part)
            if not normalized:
                continue
            candidates.append(
                ClaimCandidate(
                    raw_text=part,
                    normalized_text=normalized,
                    score=_score_claim(normalized),
                    entities=_extract_entities(normalized),
                    dates=DATE_PATTERN.findall(normalized),
                    numbers=NUMBER_PATTERN.findall(normalized),
                )
            )

        if index + 1 < len(sentences):
            next_sentence = sentences[index + 1]
            token_count = len(re.findall(r"\w+", sentence))
            combined = canonicalize_claim(f"{sentence} {next_sentence}")
            if combined and token_count <= 12 and len(combined) <= 320:
                candidates.append(
                    ClaimCandidate(
                        raw_text=f"{sentence} {next_sentence}",
                        normalized_text=combined,
                        score=_score_claim(combined) + 0.35,
                        entities=_extract_entities(combined),
                        dates=DATE_PATTERN.findall(combined),
                        numbers=NUMBER_PATTERN.findall(combined),
                        source="sentence_pair",
                    )
                )

    deduped: List[ClaimCandidate] = []
    seen = set()
    for candidate in sorted(candidates, key=lambda item: item.score, reverse=True):
        key = re.sub(r"[^a-z0-9 ]", " ", candidate.normalized_text.lower())
        key = re.sub(r"\s+", " ", key).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    strong = [candidate for candidate in deduped if candidate.score >= 2.2]
    if not strong:
        strong = deduped
    return strong[:max_claims]
