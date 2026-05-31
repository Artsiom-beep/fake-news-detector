from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .knowledge_sources import fetch_wikipedia_summary, summary_supports_property
from .schemas import ClaimCandidate, ClaimDecision, EvidenceItem, FactCheckTrace


@dataclass(frozen=True)
class KnowledgeFact:
    true_properties: frozenset[str]
    false_properties: frozenset[str]
    source_url: str
    source_title: str


@dataclass(frozen=True)
class CurrentOfficeFact:
    holder: str
    role_key: str
    role_properties: frozenset[str]
    not_current_holders: frozenset[str]
    valid_from: date
    valid_until: date
    source_url: str
    source_title: str
    source_domain: str
    source_snippet: str


@dataclass(frozen=True)
class MissionCrewFact:
    mission: str
    crew_members: frozenset[str]
    non_members: frozenset[str]
    source_url: str
    source_title: str
    source_domain: str
    source_snippet: str


COMMON_FACTS_PATH = Path(__file__).resolve().parents[2] / "data" / "factcheck" / "common_knowledge_v1.json"

CURRENT_US_PRESIDENT = CurrentOfficeFact(
    holder="donald trump",
    role_key="us_president",
    role_properties=frozenset(
        {
            "president",
            "president of united states",
            "president of the united states",
            "u s president",
            "us president",
            "american president",
        }
    ),
    not_current_holders=frozenset(
        {
            "barack obama",
            "biden",
            "joe biden",
            "joseph biden",
            "kamala harris",
            "obama",
        }
    ),
    valid_from=date(2025, 1, 20),
    valid_until=date(2029, 1, 20),
    source_url="https://www.whitehouse.gov/administration/donald-j-trump/",
    source_title="Official White House: President Donald J. Trump",
    source_domain="whitehouse.gov",
    source_snippet="Official White House administration page for President Donald J. Trump.",
)

CURRENT_UK_PRIME_MINISTER = CurrentOfficeFact(
    holder="keir starmer",
    role_key="uk_prime_minister",
    role_properties=frozenset(
        {
            "prime minister",
            "prime minister of united kingdom",
            "prime minister of the united kingdom",
            "uk prime minister",
            "british prime minister",
        }
    ),
    not_current_holders=frozenset(
        {
            "rishi sunak",
            "boris johnson",
            "liz truss",
            "theresa may",
        }
    ),
    valid_from=date(2024, 7, 5),
    valid_until=date(2026, 12, 31),
    source_url="https://www.gov.uk/government/people/keir-starmer",
    source_title="Official GOV.UK: The Rt Hon Sir Keir Starmer KCB KC MP",
    source_domain="gov.uk",
    source_snippet="GOV.UK identifies Sir Keir Starmer as Prime Minister.",
)

FEDERAL_RESERVE_CHAIR_POWELL_TERM = CurrentOfficeFact(
    holder="jerome powell",
    role_key="federal_reserve_chair",
    role_properties=frozenset(
        {
            "chair",
            "chair of federal reserve",
            "chair of the federal reserve",
            "federal reserve chair",
            "fed chair",
            "chairman of federal reserve",
            "chairman of the federal reserve",
        }
    ),
    not_current_holders=frozenset(
        {
            "ben bernanke",
            "janet yellen",
            "kevin warsh",
        }
    ),
    valid_from=date(2018, 2, 5),
    valid_until=date(2026, 5, 16),
    source_url="https://www.federalreserve.gov/aboutthefed/bios/board/powell.htm",
    source_title="Official Federal Reserve: Jerome H. Powell",
    source_domain="federalreserve.gov",
    source_snippet="The Federal Reserve identifies Jerome H. Powell as Chair.",
)

CURRENT_FEDERAL_RESERVE_CHAIR_PRO_TEMPORE = CurrentOfficeFact(
    holder="jerome powell",
    role_key="federal_reserve_chair",
    role_properties=frozenset(
        {
            "chair",
            "chair of federal reserve",
            "chair of the federal reserve",
            "chair pro tempore",
            "chair pro tempore of federal reserve",
            "chair pro tempore of the federal reserve",
            "federal reserve chair",
            "fed chair",
        }
    ),
    not_current_holders=frozenset(
        {
            "ben bernanke",
            "janet yellen",
            "kevin warsh",
        }
    ),
    valid_from=date(2026, 5, 16),
    valid_until=date(2026, 6, 16),
    source_url="https://www.federalreserve.gov/newsevents/pressreleases/other20260515a.htm",
    source_title="Official Federal Reserve: Powell named chair pro tempore",
    source_domain="federalreserve.gov",
    source_snippet=(
        "The Federal Reserve says Jerome H. Powell will serve as chair pro tempore "
        "until Kevin M. Warsh is sworn in as the new chair."
    ),
)

CURRENT_OFFICE_FACTS = (
    CURRENT_US_PRESIDENT,
    CURRENT_UK_PRIME_MINISTER,
    FEDERAL_RESERVE_CHAIR_POWELL_TERM,
    CURRENT_FEDERAL_RESERVE_CHAIR_PRO_TEMPORE,
)

CURRENT_OFFICE_SUBJECT_ALIASES = {
    "donald j trump": "donald trump",
    "donald john trump": "donald trump",
    "president donald trump": "donald trump",
    "president trump": "donald trump",
    "trump": "donald trump",
    "keir starmer kcb kc": "keir starmer",
    "sir keir starmer": "keir starmer",
    "the rt hon sir keir starmer": "keir starmer",
    "prime minister keir starmer": "keir starmer",
    "prime minister starmer": "keir starmer",
    "starmer": "keir starmer",
    "rishi sunak mp": "rishi sunak",
    "prime minister rishi sunak": "rishi sunak",
    "sunak": "rishi sunak",
    "jerome h powell": "jerome powell",
    "jerome hayden powell": "jerome powell",
    "chair jerome powell": "jerome powell",
    "chairman jerome powell": "jerome powell",
    "powell": "jerome powell",
    "kevin m warsh": "kevin warsh",
    "warsh": "kevin warsh",
}

ARTEMIS_II_CREW = MissionCrewFact(
    mission="artemis ii",
    crew_members=frozenset(
        {
            "reid wiseman",
            "victor glover",
            "christina koch",
            "jeremy hansen",
        }
    ),
    non_members=frozenset(
        {
            "elon musk",
            "mark zuckerberg",
            "jeff bezos",
        }
    ),
    source_url="https://www.nasa.gov/feature/our-artemis-crew",
    source_title="Official NASA: Our Artemis Crew",
    source_domain="nasa.gov",
    source_snippet="NASA identifies Reid Wiseman, Victor Glover, Christina Koch, and Jeremy Hansen as the Artemis II crew.",
)

MISSION_CREW_FACTS = (ARTEMIS_II_CREW,)

MISSION_CREW_MEMBER_ALIASES = {
    "christina h koch": "christina koch",
    "christina hammock koch": "christina koch",
    "g reid wiseman": "reid wiseman",
    "gregory reid wiseman": "reid wiseman",
    "victor j glover": "victor glover",
    "jeremy r hansen": "jeremy hansen",
}


DEFAULT_COMMON_FACTS: dict[str, KnowledgeFact] = {
    "apple": KnowledgeFact(
        true_properties=frozenset({"red", "green", "edible", "eatable", "fruit", "food"}),
        false_properties=frozenset({"blue", "purple", "poisonous", "dangerous", "superconductor"}),
        source_url="https://en.wikipedia.org/wiki/Apple",
        source_title="Common knowledge: apple",
    ),
    "cucumber": KnowledgeFact(
        true_properties=frozenset({"green", "edible", "eatable", "food", "vegetable"}),
        false_properties=frozenset({"purple", "red", "blue", "dangerous", "poisonous"}),
        source_url="https://en.wikipedia.org/wiki/Cucumber",
        source_title="Common knowledge: cucumber",
    ),
    "grass": KnowledgeFact(
        true_properties=frozenset({"green", "plant"}),
        false_properties=frozenset({"purple", "red", "blue", "dangerous", "poisonous", "edible", "eatable"}),
        source_url="https://en.wikipedia.org/wiki/Grass",
        source_title="Common knowledge: grass",
    ),
    "water": KnowledgeFact(
        true_properties=frozenset({"clear", "colorless", "wet", "liquid", "drinkable"}),
        false_properties=frozenset({"red", "green", "purple", "blue", "dry", "solid", "dangerous"}),
        source_url="https://en.wikipedia.org/wiki/Water",
        source_title="Common knowledge: water",
    ),
    "sky": KnowledgeFact(
        true_properties=frozenset({"blue"}),
        false_properties=frozenset({"green", "red", "purple"}),
        source_url="https://en.wikipedia.org/wiki/Sky",
        source_title="Common knowledge: sky",
    ),
    "banana": KnowledgeFact(
        true_properties=frozenset({"yellow", "edible", "eatable", "fruit", "food"}),
        false_properties=frozenset({"blue", "purple", "poisonous", "dangerous"}),
        source_url="https://en.wikipedia.org/wiki/Banana",
        source_title="Common knowledge: banana",
    ),
    "snow": KnowledgeFact(
        true_properties=frozenset({"white", "cold"}),
        false_properties=frozenset({"hot", "black", "red", "green"}),
        source_url="https://en.wikipedia.org/wiki/Snow",
        source_title="Common knowledge: snow",
    ),
    "fire": KnowledgeFact(
        true_properties=frozenset({"hot", "dangerous"}),
        false_properties=frozenset({"cold", "wet", "safe"}),
        source_url="https://en.wikipedia.org/wiki/Fire",
        source_title="Common knowledge: fire",
    ),
    "ice": KnowledgeFact(
        true_properties=frozenset({"cold", "solid"}),
        false_properties=frozenset({"hot", "warm", "liquid"}),
        source_url="https://en.wikipedia.org/wiki/Ice",
        source_title="Common knowledge: ice",
    ),
    "salt": KnowledgeFact(
        true_properties=frozenset({"salty", "edible", "eatable", "mineral"}),
        false_properties=frozenset({"sweet", "sour", "spicy"}),
        source_url="https://en.wikipedia.org/wiki/Salt",
        source_title="Common knowledge: salt",
    ),
    "sugar": KnowledgeFact(
        true_properties=frozenset({"sweet", "edible", "eatable", "food"}),
        false_properties=frozenset({"salty", "sour", "spicy", "bitter"}),
        source_url="https://en.wikipedia.org/wiki/Sugar",
        source_title="Common knowledge: sugar",
    ),
    "lemon": KnowledgeFact(
        true_properties=frozenset({"yellow", "sour", "edible", "eatable", "fruit", "food"}),
        false_properties=frozenset({"blue", "purple", "salty", "poisonous", "dangerous"}),
        source_url="https://en.wikipedia.org/wiki/Lemon",
        source_title="Common knowledge: lemon",
    ),
    "milk": KnowledgeFact(
        true_properties=frozenset({"white", "liquid", "drinkable", "edible", "eatable", "food"}),
        false_properties=frozenset({"black", "solid", "blue", "purple"}),
        source_url="https://en.wikipedia.org/wiki/Milk",
        source_title="Common knowledge: milk",
    ),
    "earth": KnowledgeFact(
        true_properties=frozenset({"planet", "round", "spherical", "orbits sun", "orbits the sun", "orbit sun", "orbit the sun"}),
        false_properties=frozenset({"flat", "star", "cube"}),
        source_url="https://en.wikipedia.org/wiki/Earth",
        source_title="Common knowledge: Earth",
    ),
    "sun": KnowledgeFact(
        true_properties=frozenset({"star", "hot"}),
        false_properties=frozenset({"cold", "planet", "orbits earth", "orbits the earth", "orbit earth", "orbit the earth"}),
        source_url="https://en.wikipedia.org/wiki/Sun",
        source_title="Common knowledge: Sun",
    ),
    "moon": KnowledgeFact(
        true_properties=frozenset({"natural satellite", "satellite", "rocky"}),
        false_properties=frozenset({"star", "planet", "cheese", "made of cheese"}),
        source_url="https://en.wikipedia.org/wiki/Moon",
        source_title="Common knowledge: Moon",
    ),
    "cat": KnowledgeFact(
        true_properties=frozenset({"animal", "mammal", "pet"}),
        false_properties=frozenset({"plant", "vegetable", "mineral"}),
        source_url="https://en.wikipedia.org/wiki/Cat",
        source_title="Common knowledge: cat",
    ),
    "dog": KnowledgeFact(
        true_properties=frozenset({"animal", "mammal", "pet"}),
        false_properties=frozenset({"plant", "vegetable", "mineral"}),
        source_url="https://en.wikipedia.org/wiki/Dog",
        source_title="Common knowledge: dog",
    ),
    "elephant": KnowledgeFact(
        true_properties=frozenset({"animal", "mammal", "large", "big"}),
        false_properties=frozenset({"insect", "small", "plant", "vegetable", "mineral"}),
        source_url="https://en.wikipedia.org/wiki/Elephant",
        source_title="Common knowledge: elephant",
    ),
    "coffee": KnowledgeFact(
        true_properties=frozenset({"drink", "beverage", "bitter", "liquid"}),
        false_properties=frozenset({"blue", "solid", "sweet"}),
        source_url="https://en.wikipedia.org/wiki/Coffee",
        source_title="Common knowledge: coffee",
    ),
    "rock": KnowledgeFact(
        true_properties=frozenset({"solid", "mineral"}),
        false_properties=frozenset({"liquid", "gas", "edible", "eatable"}),
        source_url="https://en.wikipedia.org/wiki/Rock_(geology)",
        source_title="Common knowledge: rock",
    ),
    "capital of france": KnowledgeFact(
        true_properties=frozenset({"paris"}),
        false_properties=frozenset({"berlin", "london", "rome", "madrid"}),
        source_url="https://en.wikipedia.org/wiki/Paris",
        source_title="Common knowledge: capital of France",
    ),
    "capital of germany": KnowledgeFact(
        true_properties=frozenset({"berlin"}),
        false_properties=frozenset({"paris", "london", "rome", "madrid"}),
        source_url="https://en.wikipedia.org/wiki/Berlin",
        source_title="Common knowledge: capital of Germany",
    ),
    "capital of the united kingdom": KnowledgeFact(
        true_properties=frozenset({"london"}),
        false_properties=frozenset({"paris", "berlin", "rome", "madrid"}),
        source_url="https://en.wikipedia.org/wiki/London",
        source_title="Common knowledge: capital of the United Kingdom",
    ),
    "capital of united kingdom": KnowledgeFact(
        true_properties=frozenset({"london"}),
        false_properties=frozenset({"paris", "berlin", "rome", "madrid"}),
        source_url="https://en.wikipedia.org/wiki/London",
        source_title="Common knowledge: capital of the United Kingdom",
    ),
    "capital of the united states": KnowledgeFact(
        true_properties=frozenset({"washington dc", "washington d c", "washington"}),
        false_properties=frozenset({"new york", "los angeles", "chicago", "philadelphia"}),
        source_url="https://en.wikipedia.org/wiki/Washington,_D.C.",
        source_title="Common knowledge: capital of the United States",
    ),
    "capital of united states": KnowledgeFact(
        true_properties=frozenset({"washington dc", "washington d c", "washington"}),
        false_properties=frozenset({"new york", "los angeles", "chicago", "philadelphia"}),
        source_url="https://en.wikipedia.org/wiki/Washington,_D.C.",
        source_title="Common knowledge: capital of the United States",
    ),
    "capital of usa": KnowledgeFact(
        true_properties=frozenset({"washington dc", "washington d c", "washington"}),
        false_properties=frozenset({"new york", "los angeles", "chicago", "philadelphia"}),
        source_url="https://en.wikipedia.org/wiki/Washington,_D.C.",
        source_title="Common knowledge: capital of the United States",
    ),
    "capital of u s a": KnowledgeFact(
        true_properties=frozenset({"washington dc", "washington d c", "washington"}),
        false_properties=frozenset({"new york", "los angeles", "chicago", "philadelphia"}),
        source_url="https://en.wikipedia.org/wiki/Washington,_D.C.",
        source_title="Common knowledge: capital of the United States",
    ),
    "capital of us": KnowledgeFact(
        true_properties=frozenset({"washington dc", "washington d c", "washington"}),
        false_properties=frozenset({"new york", "los angeles", "chicago", "philadelphia"}),
        source_url="https://en.wikipedia.org/wiki/Washington,_D.C.",
        source_title="Common knowledge: capital of the United States",
    ),
    "capital of u s": KnowledgeFact(
        true_properties=frozenset({"washington dc", "washington d c", "washington"}),
        false_properties=frozenset({"new york", "los angeles", "chicago", "philadelphia"}),
        source_url="https://en.wikipedia.org/wiki/Washington,_D.C.",
        source_title="Common knowledge: capital of the United States",
    ),
    "capital of the us": KnowledgeFact(
        true_properties=frozenset({"washington dc", "washington d c", "washington"}),
        false_properties=frozenset({"new york", "los angeles", "chicago", "philadelphia"}),
        source_url="https://en.wikipedia.org/wiki/Washington,_D.C.",
        source_title="Common knowledge: capital of the United States",
    ),
    "capital of america": KnowledgeFact(
        true_properties=frozenset({"washington dc", "washington d c", "washington"}),
        false_properties=frozenset({"new york", "los angeles", "chicago", "philadelphia"}),
        source_url="https://en.wikipedia.org/wiki/Washington,_D.C.",
        source_title="Common knowledge: capital of the United States",
    ),
    "capital of poland": KnowledgeFact(
        true_properties=frozenset({"warsaw"}),
        false_properties=frozenset({"krakow", "kraków", "gdansk", "gdańsk", "wroclaw", "wrocław"}),
        source_url="https://en.wikipedia.org/wiki/Warsaw",
        source_title="Common knowledge: capital of Poland",
    ),
}


def _load_common_facts(path: Path = COMMON_FACTS_PATH) -> dict[str, KnowledgeFact]:
    merged = dict(DEFAULT_COMMON_FACTS)
    if not path.exists():
        return merged
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        facts = payload.get("facts", {})
        for subject, item in facts.items():
            merged[_normalize_phrase(subject)] = KnowledgeFact(
                true_properties=frozenset(_normalize_phrase(value) for value in item.get("true_properties", [])),
                false_properties=frozenset(_normalize_phrase(value) for value in item.get("false_properties", [])),
                source_url=item.get("source_url", ""),
                source_title=item.get("source_title", f"Common knowledge: {subject}"),
            )
        return merged
    except Exception:
        return merged

PROPERTY_ALIASES = {
    "eatable": "edible",
    "safe to eat": "edible",
    "not dangerous": "safe",
    "not safe": "dangerous",
}

NUMBER_PATTERN = r"-?\d+(?:\.\d+)?"

UNIT_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}

TENS_NUMBER_WORDS = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

NUMBER_WORD_PATTERN = (
    r"(?:"
    + "|".join(re.escape(word) for word in [*UNIT_NUMBER_WORDS, *TENS_NUMBER_WORDS])
    + r")(?:[-\s]+(?:"
    + "|".join(re.escape(word) for word in list(UNIT_NUMBER_WORDS)[1:10])
    + r"))?"
)
NUMBER_VALUE_PATTERN = rf"(?:{NUMBER_PATTERN}|{NUMBER_WORD_PATTERN})"

COMPARISON_ALIASES = {
    ">": "greater_than",
    "greater than": "greater_than",
    "more than": "greater_than",
    "larger than": "greater_than",
    "bigger than": "greater_than",
    "higher than": "greater_than",
    "above": "greater_than",
    "<": "less_than",
    "less than": "less_than",
    "smaller than": "less_than",
    "lower than": "less_than",
    "fewer than": "less_than",
    "below": "less_than",
    "under": "less_than",
    "=": "equal_to",
    "==": "equal_to",
    "equals": "equal_to",
    "equal to": "equal_to",
    "same as": "equal_to",
    "at least": "at_least",
    ">=": "at_least",
    "no less than": "at_least",
    "at most": "at_most",
    "<=": "at_most",
    "no more than": "at_most",
}

ARITHMETIC_OPERATOR_ALIASES = {
    "+": "plus",
    "plus": "plus",
    "add": "plus",
    "added to": "plus",
    "-": "minus",
    "minus": "minus",
    "subtract": "minus",
    "subtracted by": "minus",
    "*": "times",
    "x": "times",
    "times": "times",
    "multiplied by": "times",
    "/": "divided_by",
    "÷": "divided_by",
    "divided by": "divided_by",
}

RELATION_VERBS = {
    "cause",
    "causes",
    "cure",
    "cures",
    "include",
    "includes",
    "orbit",
    "orbits",
    "prevent",
    "prevents",
    "treat",
    "treats",
}


def _normalize_phrase(text: str) -> str:
    text = re.sub(r"[^a-z0-9\s-]", " ", (text or "").lower())
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\be\s*minister\b", "minister", text)
    text = re.sub(r"^(a|an|the)\s+", "", text)
    return PROPERTY_ALIASES.get(text, text)


COMMON_FACTS: dict[str, KnowledgeFact] = _load_common_facts()


def _subject_variants(subject: str) -> list[str]:
    variants = [subject]
    if subject.endswith("ies") and len(subject) > 4:
        variants.append(f"{subject[:-3]}y")
    if subject.endswith("s") and len(subject) > 3:
        variants.append(subject[:-1])
    return variants


def _phrase_variants(phrase: str) -> set[str]:
    variants = {phrase}
    tokens = phrase.split()
    if not tokens:
        return variants
    last = tokens[-1]
    last_variants = set(_subject_variants(last))
    if last.endswith("y") and len(last) > 3:
        last_variants.add(f"{last[:-1]}ies")
    elif not last.endswith("s"):
        last_variants.add(f"{last}s")
    for candidate in last_variants:
        variants.add(" ".join([*tokens[:-1], candidate]))
    return variants


def _property_in(prop: str, values: frozenset[str]) -> bool:
    return bool(_phrase_variants(prop) & set(values))


def _normalize_current_office_subject(subject: str) -> str:
    normalized = _normalize_phrase(subject)
    return CURRENT_OFFICE_SUBJECT_ALIASES.get(normalized, normalized)


def _normalize_mission_member(member: str) -> str:
    normalized = _normalize_phrase(member)
    return MISSION_CREW_MEMBER_ALIASES.get(normalized, normalized)


def _mission_subject_matches(subject: str, mission: str) -> bool:
    normalized = _normalize_phrase(subject)
    accepted = {
        mission,
        f"{mission} crew",
        f"{mission} mission",
        f"{mission} astronauts",
    }
    return normalized in accepted


def _property_is_current_office_role(prop: str, office: CurrentOfficeFact) -> bool:
    normalized = _normalize_phrase(prop)
    return bool(_phrase_variants(normalized) & set(office.role_properties))


def _current_office_in_effect(office: CurrentOfficeFact) -> bool:
    today = date.today()
    return office.valid_from <= today < office.valid_until


def _decide_current_office_statement(
    claim: ClaimCandidate,
    subject: str,
    properties: list[tuple[str, bool]],
    trace: FactCheckTrace,
) -> ClaimDecision | None:
    if not properties:
        return None

    matched_office: CurrentOfficeFact | None = None
    for office in CURRENT_OFFICE_FACTS:
        if _current_office_in_effect(office) and all(
            _property_is_current_office_role(prop, office) for prop, _ in properties
        ):
            matched_office = office
            break
    if matched_office is None:
        return None

    normalized_subject = _normalize_current_office_subject(subject)
    if normalized_subject == matched_office.holder:
        statement_is_true = all(not negated for _, negated in properties)
    elif normalized_subject in matched_office.not_current_holders:
        statement_is_true = all(negated for _, negated in properties)
    else:
        return None

    verdict = "true" if statement_is_true else "fake"
    stance = "support" if statement_is_true else "refute"
    support_score = 0.94 if statement_is_true else 0.0
    refute_score = 0.94 if not statement_is_true else 0.0
    role_text = ", ".join(prop for prop, _ in properties)
    holder_display = matched_office.holder.title()
    passage = (
        f"{matched_office.source_snippet.rstrip('.')}. The official source identifies {holder_display} "
        f"as the current holder of this role, so the claim about {role_text} is "
        f"{'supported' if statement_is_true else 'refuted'}."
    )
    evidence = EvidenceItem(
        url=matched_office.source_url,
        title=matched_office.source_title,
        stance=stance,
        score=0.94,
        snippet=matched_office.source_snippet,
        passage=passage,
        source_type="official_government",
        source_trust=0.97,
        relevance=0.98,
        freshness=0.9,
        domain=matched_office.source_domain,
        verdict_source="current_office_registry_v1",
        claim_match_score=1.0,
    )
    reasons = [
        "strategy=current_office",
        f"current_office_role={matched_office.role_key}",
        f"current_office_holder={matched_office.holder}",
        f"current_office_verdict={verdict}",
    ]
    _record_trace(claim, trace, reasons, evidence)
    return ClaimDecision(
        claim=claim,
        verdict=verdict,
        confidence=0.94,
        support_score=support_score,
        refute_score=refute_score,
        neutral_score=0.0,
        independent_sources=1,
        trusted_hits=1,
        reasons=reasons,
        evidence=[evidence],
    )


def _decide_mission_crew_statement(
    claim: ClaimCandidate,
    subject: str,
    properties: list[tuple[str, bool]],
    trace: FactCheckTrace,
) -> ClaimDecision | None:
    if not properties:
        return None

    matched_fact: MissionCrewFact | None = None
    for fact in MISSION_CREW_FACTS:
        if _mission_subject_matches(subject, fact.mission):
            matched_fact = fact
            break
    if matched_fact is None:
        return None

    member_truths: list[bool] = []
    checked_members: list[str] = []
    for prop, negated in properties:
        match = re.match(r"^(?:include|includes)\s+(?P<member>.+)$", _normalize_phrase(prop))
        if not match:
            return None
        member = _normalize_mission_member(match.group("member"))
        if member in matched_fact.crew_members:
            member_truths.append(not negated)
        elif member in matched_fact.non_members:
            member_truths.append(negated)
        else:
            return None
        checked_members.append(member)

    statement_is_true = all(member_truths)
    verdict = "true" if statement_is_true else "fake"
    stance = "support" if statement_is_true else "refute"
    support_score = 0.94 if statement_is_true else 0.0
    refute_score = 0.94 if not statement_is_true else 0.0
    members_text = ", ".join(checked_members)
    passage = (
        f"{matched_fact.source_snippet.rstrip('.')}. Based on that official crew list, "
        f"the claim about {members_text} is {'supported' if statement_is_true else 'refuted'}."
    )
    evidence = EvidenceItem(
        url=matched_fact.source_url,
        title=matched_fact.source_title,
        stance=stance,
        score=0.94,
        snippet=matched_fact.source_snippet,
        passage=passage,
        source_type="official_government",
        source_trust=0.97,
        relevance=0.98,
        freshness=0.9,
        domain=matched_fact.source_domain,
        verdict_source="mission_crew_registry_v1",
        claim_match_score=1.0,
    )
    reasons = [
        "strategy=mission_crew",
        f"mission={matched_fact.mission}",
        f"mission_crew_members={members_text}",
        f"mission_crew_verdict={verdict}",
    ]
    _record_trace(claim, trace, reasons, evidence)
    return ClaimDecision(
        claim=claim,
        verdict=verdict,
        confidence=0.94,
        support_score=support_score,
        refute_score=refute_score,
        neutral_score=0.0,
        independent_sources=1,
        trusted_hits=1,
        reasons=reasons,
        evidence=[evidence],
    )


def _lookup_common_fact(subject: str) -> tuple[str, KnowledgeFact | None]:
    for candidate in _subject_variants(subject):
        fact = COMMON_FACTS.get(candidate)
        if fact is not None:
            return candidate, fact
    return subject, None


def _record_trace(
    claim: ClaimCandidate,
    trace: FactCheckTrace,
    reasons: list[str],
    evidence: EvidenceItem | None = None,
) -> None:
    trace.decision_reasons.extend([f"{claim.normalized_text}: {item}" for item in reasons])
    if evidence is not None:
        trace.selected_passages.append(
            {
                "url": evidence.url,
                "title": evidence.title,
                "stance": evidence.stance,
                "score": round(evidence.score, 4),
                "passage": evidence.passage,
            }
        )


def _uncertain_knowledge_decision(
    claim: ClaimCandidate,
    trace: FactCheckTrace,
    subject: str,
    reason: str,
    evidence: EvidenceItem | None = None,
    confidence: float = 0.3,
) -> ClaimDecision:
    reasons = [
        "strategy=common_knowledge",
        f"common_knowledge_subject={subject}",
        reason,
        "hard_verdict_policy=no_exact_answer",
    ]
    trace.fallbacks_used.append("knowledge_no_exact_answer")
    _record_trace(claim, trace, reasons, evidence)
    return ClaimDecision(
        claim=claim,
        verdict="uncertain",
        confidence=confidence,
        support_score=0.0,
        refute_score=0.0,
        neutral_score=evidence.score if evidence is not None else 0.3,
        independent_sources=1 if evidence is not None else 0,
        trusted_hits=0,
        reasons=reasons,
        evidence=[evidence] if evidence is not None else [],
    )


def _format_decimal(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(value.quantize(Decimal("1")))
    return format(value.normalize(), "f")


def _parse_number_value(value: str) -> Decimal:
    normalized = re.sub(r"[-\s]+", " ", (value or "").strip().lower())
    try:
        return Decimal(normalized)
    except InvalidOperation:
        pass

    parts = normalized.split()
    if not parts:
        raise InvalidOperation
    if len(parts) == 1 and parts[0] in UNIT_NUMBER_WORDS:
        return Decimal(UNIT_NUMBER_WORDS[parts[0]])
    if len(parts) == 1 and parts[0] in TENS_NUMBER_WORDS:
        return Decimal(TENS_NUMBER_WORDS[parts[0]])
    if len(parts) == 2 and parts[0] in TENS_NUMBER_WORDS and parts[1] in UNIT_NUMBER_WORDS:
        return Decimal(TENS_NUMBER_WORDS[parts[0]] + UNIT_NUMBER_WORDS[parts[1]])
    raise InvalidOperation


def _compare_numbers(left: Decimal, operator: str, right: Decimal) -> bool:
    if operator == "greater_than":
        return left > right
    if operator == "less_than":
        return left < right
    if operator == "equal_to":
        return left == right
    if operator == "at_least":
        return left >= right
    if operator == "at_most":
        return left <= right
    raise ValueError(f"Unsupported comparison operator: {operator}")


def _evaluate_arithmetic(left: Decimal, operator: str, right: Decimal) -> Decimal | None:
    if operator == "plus":
        return left + right
    if operator == "minus":
        return left - right
    if operator == "times":
        return left * right
    if operator == "divided_by":
        if right == 0:
            return None
        return left / right
    raise ValueError(f"Unsupported arithmetic operator: {operator}")


def _split_arithmetic_equation(claim_text: str) -> tuple[Decimal, str, Decimal, Decimal] | None:
    text = re.sub(r"\s+", " ", (claim_text or "").strip().lower())
    text = text.rstrip(".!?")
    symbol_match = re.match(
        rf"^(?P<left>{NUMBER_VALUE_PATTERN})\s*"
        rf"(?P<operator>\+|-|\*|x|/|÷)\s*"
        rf"(?P<right>{NUMBER_VALUE_PATTERN})\s*(?:=|==|equals?|equal to|is)\s*"
        rf"(?P<result>{NUMBER_VALUE_PATTERN})$",
        text,
    )
    word_match = re.match(
        rf"^(?P<left>{NUMBER_VALUE_PATTERN})\s+"
        rf"(?P<operator>plus|add|added to|minus|subtract|subtracted by|times|multiplied by|divided by)\s+"
        rf"(?P<right>{NUMBER_VALUE_PATTERN})\s+(?:=|==|equals?|equal to|is)\s+"
        rf"(?P<result>{NUMBER_VALUE_PATTERN})$",
        text,
    )
    match = symbol_match or word_match
    if not match:
        return None
    try:
        left = _parse_number_value(match.group("left"))
        right = _parse_number_value(match.group("right"))
        result = _parse_number_value(match.group("result"))
    except (InvalidOperation, TypeError):
        return None
    operator = ARITHMETIC_OPERATOR_ALIASES[match.group("operator")]
    return left, operator, right, result


def _split_numeric_comparison(claim_text: str) -> tuple[Decimal, str, Decimal, bool] | None:
    text = re.sub(r"\s+", " ", (claim_text or "").strip().lower())
    text = text.rstrip(".!?")
    symbol_match = re.match(
        rf"^(?P<left>{NUMBER_VALUE_PATTERN})\s*(?P<operator>>=|<=|==|>|<|=)\s*(?P<right>{NUMBER_VALUE_PATTERN})$",
        text,
    )
    word_match = re.match(
        rf"^(?P<left>{NUMBER_VALUE_PATTERN})\s+(?:is\s+)?(?P<negated>not\s+)?"
        rf"(?P<operator>no less than|no more than|greater than|more than|larger than|"
        rf"bigger than|higher than|less than|smaller than|lower than|fewer than|"
        rf"equal to|equals|same as|at least|at most|above|below|under)\s+"
        rf"(?P<right>{NUMBER_VALUE_PATTERN})$",
        text,
    )
    match = symbol_match or word_match
    if not match:
        return None
    try:
        left = _parse_number_value(match.group("left"))
        right = _parse_number_value(match.group("right"))
    except (InvalidOperation, TypeError):
        return None
    operator = COMPARISON_ALIASES[match.group("operator")]
    negated = bool(match.groupdict().get("negated"))
    return left, operator, right, negated


def _decide_numeric_comparison(
    claim: ClaimCandidate,
    trace: FactCheckTrace,
) -> ClaimDecision | None:
    equation = _split_arithmetic_equation(claim.normalized_text)
    if equation is not None:
        left, operator, right, expected_result = equation
        actual_result = _evaluate_arithmetic(left, operator, right)
        if actual_result is None:
            return _uncertain_knowledge_decision(
                claim=claim,
                trace=trace,
                subject="arithmetic",
                reason="arithmetic_no_exact_answer=division_by_zero",
                evidence=None,
                confidence=0.24,
            )
        comparison_result = actual_result == expected_result
        verdict = "true" if comparison_result else "fake"
        stance = "support" if comparison_result else "refute"
        support_score = 0.97 if comparison_result else 0.0
        refute_score = 0.97 if not comparison_result else 0.0
        left_text = _format_decimal(left)
        right_text = _format_decimal(right)
        expected_text = _format_decimal(expected_result)
        actual_text = _format_decimal(actual_result)
        operator_text = operator.replace("_", " ")
        reason = (
            f"arithmetic_equation_{'supports' if comparison_result else 'refutes'}="
            f"{left_text} {operator_text} {right_text} equals {actual_text}"
        )
        passage = (
            f"Local arithmetic check: {left_text} {operator_text} {right_text} "
            f"equals {actual_text}, so the claimed result {expected_text} is "
            f"{str(comparison_result).lower()}."
        )
        evidence = EvidenceItem(
            url="https://en.wikipedia.org/wiki/Arithmetic",
            title="Local arithmetic equation",
            stance=stance,
            score=0.97,
            snippet="The best-accuracy pipeline evaluates simple arithmetic equations locally.",
            passage=passage,
            source_type="local_arithmetic",
            source_trust=0.98,
            relevance=1.0,
            freshness=1.0,
            domain="local_arithmetic",
            verdict_source="local_arithmetic_v1",
            claim_match_score=1.0,
        )
        reasons = [
            "strategy=common_knowledge",
            "common_knowledge_subject=arithmetic",
            reason,
        ]
        trace.decision_reasons.extend([f"{claim.normalized_text}: {item}" for item in reasons])
        trace.selected_passages.append(
            {
                "url": evidence.url,
                "title": evidence.title,
                "stance": evidence.stance,
                "score": round(evidence.score, 4),
                "passage": evidence.passage,
            }
        )
        return ClaimDecision(
            claim=claim,
            verdict=verdict,
            confidence=0.97,
            support_score=support_score,
            refute_score=refute_score,
            neutral_score=0.0,
            independent_sources=1,
            trusted_hits=1,
            reasons=reasons,
            evidence=[evidence],
        )

    parsed = _split_numeric_comparison(claim.normalized_text)
    if parsed is None:
        return None
    left, operator, right, negated = parsed
    comparison_result = _compare_numbers(left, operator, right)
    if negated:
        comparison_result = not comparison_result

    verdict = "true" if comparison_result else "fake"
    stance = "support" if comparison_result else "refute"
    support_score = 0.97 if comparison_result else 0.0
    refute_score = 0.97 if not comparison_result else 0.0
    left_text = _format_decimal(left)
    right_text = _format_decimal(right)
    operator_text = operator.replace("_", " ")
    negation_text = "not " if negated else ""
    reason = f"arithmetic_{'supports' if comparison_result else 'refutes'}={left_text} {negation_text}{operator_text} {right_text}"
    passage = (
        f"Local arithmetic check: {left_text} is {negation_text}{operator_text} "
        f"{right_text} is {str(comparison_result).lower()}."
    )
    evidence = EvidenceItem(
        url="https://en.wikipedia.org/wiki/Arithmetic",
        title="Local arithmetic comparison",
        stance=stance,
        score=0.97,
        snippet="The best-accuracy pipeline evaluates simple numeric comparisons locally.",
        passage=passage,
        source_type="local_arithmetic",
        source_trust=0.98,
        relevance=1.0,
        freshness=1.0,
        domain="local_arithmetic",
        verdict_source="local_arithmetic_v1",
        claim_match_score=1.0,
    )
    reasons = [
        "strategy=common_knowledge",
        "common_knowledge_subject=arithmetic",
        reason,
    ]
    trace.decision_reasons.extend([f"{claim.normalized_text}: {item}" for item in reasons])
    trace.selected_passages.append(
        {
            "url": evidence.url,
            "title": evidence.title,
            "stance": evidence.stance,
            "score": round(evidence.score, 4),
            "passage": evidence.passage,
        }
    )
    return ClaimDecision(
        claim=claim,
        verdict=verdict,
        confidence=0.97,
        support_score=support_score,
        refute_score=refute_score,
        neutral_score=0.0,
        independent_sources=1,
        trusted_hits=1,
        reasons=reasons,
        evidence=[evidence],
    )


def _split_statement(claim_text: str) -> tuple[str, list[tuple[str, bool]]] | None:
    text = _normalize_phrase(claim_text)
    match = re.match(r"^(?P<subject>[a-z0-9 -]+?)\s+(?:is|are|was|were)\s+(?P<props>.+)$", text)
    if not match:
        relation_match = re.match(
            r"^(?P<subject>[a-z0-9 -]+?)\s+"
            r"(?P<verb>causes?|cures?|includes?|orbits?|prevents?|treats?)\s+"
            r"(?P<object>.+)$",
            text,
        )
        if relation_match:
            subject = _normalize_phrase(relation_match.group("subject"))
            prop = _normalize_phrase(f"{relation_match.group('verb')} {relation_match.group('object')}")
            return (subject, [(prop, False)]) if subject and prop else None
    if not match:
        return None
    subject = _normalize_phrase(match.group("subject"))
    props_text = match.group("props")
    raw_props = re.split(r"\s*(?:,|;|\band\b|\bbut\b)\s*(?:is|are|was|were)?\s*", props_text)
    properties: list[tuple[str, bool]] = []
    for raw_prop in raw_props:
        prop = _normalize_phrase(raw_prop)
        if not prop:
            continue
        negated = False
        if prop.startswith("not "):
            negated = True
            prop = _normalize_phrase(prop[4:])
        properties.append((prop, negated))
    if not subject or not properties:
        return None
    return subject, properties


def _contains_relation_property(properties: list[tuple[str, bool]]) -> bool:
    return any(prop.split(" ", 1)[0] in RELATION_VERBS for prop, _ in properties)


def _decide_source_backed_statement(
    claim: ClaimCandidate,
    subject: str,
    properties: list[tuple[str, bool]],
    trace: FactCheckTrace,
) -> ClaimDecision | None:
    summary = fetch_wikipedia_summary(subject)
    if summary is None:
        return _uncertain_knowledge_decision(
            claim=claim,
            trace=trace,
            subject=subject,
            reason="knowledge_source_unavailable=wikipedia_summary",
            evidence=None,
            confidence=0.26,
        )

    supported: list[str] = []
    unknown: list[str] = []
    refuted_by_negation: list[str] = []
    for prop, negated in properties:
        if summary_supports_property(summary, prop):
            if negated:
                refuted_by_negation.append(prop)
            else:
                supported.append(prop)
        else:
            unknown.append(prop)

    if not supported and not refuted_by_negation:
        prop_text = ", ".join(prop for prop, _ in properties)
        evidence = EvidenceItem(
            url=summary.url,
            title=f"Wikipedia summary: {summary.title}",
            stance="neutral",
            score=0.42,
            snippet=summary.extract[:320],
            passage=(
                f"Wikipedia summary for {summary.title} was checked, but it does not give an exact "
                f"answer for: {prop_text}."
            ),
            source_type="knowledge_source",
            source_trust=0.82,
            relevance=0.62,
            freshness=0.65,
            domain="wikipedia.org",
            verdict_source=summary.source,
            claim_match_score=0.48,
        )
        return _uncertain_knowledge_decision(
            claim=claim,
            trace=trace,
            subject=subject,
            reason=f"wikipedia_summary_no_exact_answer={prop_text}",
            evidence=evidence,
            confidence=0.34,
        )

    if refuted_by_negation:
        verdict = "fake"
        confidence = 0.72
        stance = "refute"
        support_score = 0.0
        refute_score = 0.78
        reason = f"wikipedia_summary_refutes_negation={','.join(refuted_by_negation)}"
        passage = f"Wikipedia summary for {summary.title} supports {', '.join(refuted_by_negation)}, contrary to the negated claim."
    elif unknown:
        verdict = "uncertain"
        confidence = 0.38
        stance = "neutral"
        support_score = 0.45
        refute_score = 0.0
        reason = f"wikipedia_summary_partial_support={','.join(supported)};unknown={','.join(unknown)}"
        passage = f"Wikipedia summary for {summary.title} supports {', '.join(supported)}, but does not clearly cover {', '.join(unknown)}."
    else:
        verdict = "true"
        confidence = 0.74
        stance = "support"
        support_score = 0.78
        refute_score = 0.0
        reason = f"wikipedia_summary_supports={','.join(supported)}"
        passage = f"Wikipedia summary for {summary.title} supports: {', '.join(supported)}."

    evidence = EvidenceItem(
        url=summary.url,
        title=f"Wikipedia summary: {summary.title}",
        stance=stance,
        score=max(support_score, refute_score, 0.45),
        snippet=summary.extract[:320],
        passage=passage,
        source_type="knowledge_source",
        source_trust=0.82,
        relevance=0.86,
        freshness=0.65,
        domain="wikipedia.org",
        verdict_source=summary.source,
        claim_match_score=0.78,
    )
    reasons = [
        "strategy=common_knowledge",
        f"knowledge_source_subject={subject}",
        reason,
    ]
    _record_trace(claim, trace, reasons, evidence)
    return ClaimDecision(
        claim=claim,
        verdict=verdict,
        confidence=confidence,
        support_score=support_score,
        refute_score=refute_score,
        neutral_score=0.0 if verdict != "uncertain" else 0.45,
        independent_sources=1,
        trusted_hits=1,
        reasons=reasons,
        evidence=[evidence],
    )


def decide_common_knowledge(
    claim: ClaimCandidate,
    trace: FactCheckTrace,
) -> ClaimDecision | None:
    numeric_decision = _decide_numeric_comparison(claim, trace=trace)
    if numeric_decision is not None:
        return numeric_decision

    parsed = _split_statement(claim.normalized_text)
    if parsed is None:
        return None
    subject, properties = parsed
    current_office_decision = _decide_current_office_statement(claim, subject, properties, trace)
    if current_office_decision is not None:
        return current_office_decision

    mission_crew_decision = _decide_mission_crew_statement(claim, subject, properties, trace)
    if mission_crew_decision is not None:
        return mission_crew_decision

    subject, fact = _lookup_common_fact(subject)
    if fact is None:
        return _decide_source_backed_statement(claim, subject, properties, trace)

    supported: list[str] = []
    refuted: list[str] = []
    unknown: list[str] = []

    for prop, negated in properties:
        if _property_in(prop, fact.true_properties):
            (refuted if negated else supported).append(prop)
        elif _property_in(prop, fact.false_properties):
            (supported if negated else refuted).append(prop)
        else:
            unknown.append(prop)

    if not supported and not refuted:
        if _contains_relation_property(properties):
            return _decide_source_backed_statement(claim, subject, properties, trace)
        unknown_text = ", ".join(unknown)
        evidence = EvidenceItem(
            url=fact.source_url,
            title=fact.source_title,
            stance="neutral",
            score=0.4,
            snippet="The local common-knowledge base was checked, but it does not contain this exact property.",
            passage=(
                f"Local common-knowledge rules cover {subject}, but they do not give an exact "
                f"answer for: {unknown_text}."
            ),
            source_type="common_knowledge",
            source_trust=0.72,
            relevance=0.72,
            freshness=0.55,
            domain="local_common_knowledge",
            verdict_source="local_common_knowledge_v1",
            claim_match_score=0.66,
        )
        return _uncertain_knowledge_decision(
            claim=claim,
            trace=trace,
            subject=subject,
            reason=f"common_knowledge_no_exact_answer={unknown_text}",
            evidence=evidence,
            confidence=0.32,
        )

    if refuted:
        verdict = "fake"
        confidence = 0.78 if not unknown else 0.68
        stance = "refute"
        reason = f"common_knowledge_refutes={','.join(refuted)}"
        passage = (
            f"Local common-knowledge rules mark {subject} as not matching: "
            f"{', '.join(refuted)}."
        )
        support_score = 0.0
        refute_score = 0.86
    elif unknown:
        verdict = "uncertain"
        confidence = 0.36
        stance = "neutral"
        reason = f"common_knowledge_partial_unknown={','.join(unknown)}"
        passage = (
            f"Local common-knowledge rules support {', '.join(supported)}, "
            f"but do not cover: {', '.join(unknown)}."
        )
        support_score = 0.45
        refute_score = 0.0
    else:
        verdict = "true"
        confidence = 0.82
        stance = "support"
        reason = f"common_knowledge_supports={','.join(supported)}"
        passage = (
            f"Local common-knowledge rules mark {subject} as matching: "
            f"{', '.join(supported)}."
        )
        support_score = 0.88
        refute_score = 0.0

    evidence = EvidenceItem(
        url=fact.source_url,
        title=fact.source_title,
        stance=stance,
        score=max(support_score, refute_score, 0.45),
        snippet="The best-accuracy pipeline uses a small local rule base for simple everyday facts.",
        passage=passage,
        source_type="common_knowledge",
        source_trust=0.72,
        relevance=0.95,
        freshness=0.55,
        domain="local_common_knowledge",
        verdict_source="local_common_knowledge_v1",
        claim_match_score=1.0,
    )
    reasons = [
        "strategy=common_knowledge",
        f"common_knowledge_subject={subject}",
        reason,
    ]
    _record_trace(claim, trace, reasons, evidence)
    return ClaimDecision(
        claim=claim,
        verdict=verdict,
        confidence=confidence,
        support_score=support_score,
        refute_score=refute_score,
        neutral_score=0.0 if verdict != "uncertain" else 0.45,
        independent_sources=1,
        trusted_hits=0,
        reasons=reasons,
        evidence=[evidence],
    )
