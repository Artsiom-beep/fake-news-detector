from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

# Keep this acceptance suite lightweight and deterministic. The optional
# HuggingFace image model is evaluated by a separate benchmark.
os.environ["FACTCHECK_AI_IMAGE_MODEL"] = "metadata_only"

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont, PngImagePlugin

from src.factcheck.config import build_config
from src.factcheck.image_analysis import run_ai_image_check, run_screenshot_factcheck
from src.factcheck.news_credibility import analyze_news_credibility
from src.factcheck.schemas import FactCheckTrace
from src.factcheck.service import run_factcheck


DEFAULT_OUT_JSON = ROOT / "reports" / "product_acceptance_latest.json"
DEFAULT_OUT_MD = ROOT / "reports" / "product_acceptance_latest.md"
TARGET_PASS_RATE = 0.95
MIN_CASES_PER_SECTION = 5
MIN_CASES_BY_SECTION = {
    "facts": 40,
    "news": 15,
    "screenshots": 12,
    "images": 11,
    "api_contract": 11,
}


CaseCheck = Callable[[dict[str, Any]], tuple[bool, str]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _min_cases_for_section(section: str) -> int:
    return MIN_CASES_BY_SECTION.get(section, MIN_CASES_PER_SECTION)


def _check_verdict(expected: str) -> CaseCheck:
    def check(payload: dict[str, Any]) -> tuple[bool, str]:
        actual = str(payload.get("verdict", ""))
        return actual == expected, f"expected verdict={expected}, got {actual}"

    return check


def _check_credibility_label(*allowed: str) -> CaseCheck:
    allowed_set = set(allowed)

    def check(payload: dict[str, Any]) -> tuple[bool, str]:
        credibility = payload.get("credibility") or {}
        actual = str(credibility.get("label", ""))
        return actual in allowed_set, f"expected credibility in {sorted(allowed_set)}, got {actual}"

    return check


def _check_ai_label(*allowed: str) -> CaseCheck:
    allowed_set = set(allowed)

    def check(payload: dict[str, Any]) -> tuple[bool, str]:
        image_analysis = payload.get("image_analysis") or {}
        actual = str(image_analysis.get("ai_label", ""))
        return actual in allowed_set, f"expected ai_label in {sorted(allowed_set)}, got {actual}"

    return check


def _check_status(expected: str) -> CaseCheck:
    def check(payload: dict[str, Any]) -> tuple[bool, str]:
        actual = str(payload.get("status", ""))
        return actual == expected, f"expected status={expected}, got {actual}"

    return check


def _public(result: Any) -> dict[str, Any]:
    return result.to_public_dict()


def _run_fact_cases() -> list[dict[str, Any]]:
    cases: list[tuple[str, str, CaseCheck]] = [
        ("fact_arithmetic_true", "2 plus 2 equals 4", _check_verdict("true")),
        ("fact_arithmetic_false", "2 plus 2 equals 5", _check_verdict("fake")),
        ("fact_word_arithmetic_true", "Two plus two equals four", _check_verdict("true")),
        ("fact_word_arithmetic_false", "Ten divided by two equals three", _check_verdict("fake")),
        ("fact_arithmetic_multiplication_true", "3 times 7 equals 21", _check_verdict("true")),
        ("fact_arithmetic_division_false", "10 divided by 2 equals 3", _check_verdict("fake")),
        ("fact_arithmetic_addition_false", "5 + 5 = 11", _check_verdict("fake")),
        ("fact_numeric_true", "100 is lower than 200", _check_verdict("true")),
        ("fact_numeric_false", "100 > 200", _check_verdict("fake")),
        ("fact_numeric_less_true", "15 is less than 20", _check_verdict("true")),
        ("fact_symbolic_comparison_true", "20 >= 15", _check_verdict("true")),
        ("fact_word_numeric_true", "Five is greater than three", _check_verdict("true")),
        ("fact_elephant_mammal", "Elephants are mammals.", _check_verdict("true")),
        ("fact_elephant_insect", "Elephants are insects.", _check_verdict("fake")),
        ("fact_dog_mammal", "Dogs are mammals.", _check_verdict("true")),
        ("fact_cat_plant", "Cats are plants.", _check_verdict("fake")),
        ("fact_apple_food", "An apple is food.", _check_verdict("true")),
        ("fact_apple_blue", "An apple is blue.", _check_verdict("fake")),
        ("fact_banana_yellow", "Bananas are yellow.", _check_verdict("true")),
        ("fact_banana_blue", "Bananas are blue.", _check_verdict("fake")),
        ("fact_cucumber_green", "Cucumbers are green.", _check_verdict("true")),
        ("fact_grass_red", "Grass is red.", _check_verdict("fake")),
        ("fact_water_liquid", "Water is liquid.", _check_verdict("true")),
        ("fact_ice_hot", "Ice is hot.", _check_verdict("fake")),
        ("fact_fire_hot", "Fire is hot.", _check_verdict("true")),
        ("fact_snow_cold", "Snow is cold.", _check_verdict("true")),
        ("fact_snow_black", "Snow is black.", _check_verdict("fake")),
        ("fact_rock_edible", "A rock is edible.", _check_verdict("fake")),
        ("fact_capital_true", "The capital of France is Paris.", _check_verdict("true")),
        ("fact_capital_false", "The capital of France is Berlin.", _check_verdict("fake")),
        ("fact_capital_germany_true", "The capital of Germany is Berlin.", _check_verdict("true")),
        ("fact_capital_us_false", "The capital of the United States is New York.", _check_verdict("fake")),
        ("fact_capital_usa_true", "The capital of USA is Washington DC.", _check_verdict("true")),
        ("fact_capital_poland_true", "The capital of Poland is Warsaw.", _check_verdict("true")),
        ("fact_orbit_true", "Earth orbits the Sun.", _check_verdict("true")),
        ("fact_orbit_false", "The Sun orbits the Earth.", _check_verdict("fake")),
        ("fact_moon_satellite", "The Moon is a natural satellite.", _check_verdict("true")),
        ("fact_moon_cheese", "The Moon is made of cheese.", _check_verdict("fake")),
        ("fact_sky_blue", "The sky is blue.", _check_verdict("true")),
        ("fact_sky_green", "The sky is green.", _check_verdict("fake")),
        ("fact_taste_false", "Salt is sweet.", _check_verdict("fake")),
        ("fact_taste_true", "Sugar is sweet.", _check_verdict("true")),
        ("fact_medical_abstain", "Coffee cures cancer.", _check_verdict("uncertain")),
        ("fact_unsourced_abstain", "An unverified forum post proves a secret cure works.", _check_verdict("uncertain")),
    ]
    rows: list[dict[str, Any]] = []
    for case_id, text, checker in cases:
        payload = _public(run_factcheck(text=text))
        passed, detail = checker(payload)
        rows.append(
            {
                "id": case_id,
                "section": "facts",
                "input": text,
                "passed": passed,
                "detail": detail,
                "verdict": payload.get("verdict"),
                "confidence": payload.get("confidence"),
                "summary": payload.get("summary"),
            }
        )
    return rows


@contextmanager
def _patched_news_search(fake_hits: dict[str, list[dict[str, str]]]):
    import src.factcheck.news_credibility as news_module

    original = news_module.search_web

    def fake_search(query: str, count: int = 5, cache=None):
        low = query.lower()
        for marker, hits in fake_hits.items():
            if marker in low:
                return hits[:count]
        return []

    news_module.search_web = fake_search
    try:
        yield
    finally:
        news_module.search_web = original


def _news_payload(text: str, url: str, fetched: dict[str, Any], fake_hits: dict[str, list[dict[str, str]]]):
    with _patched_news_search(fake_hits):
        return _public(analyze_news_credibility(text, url, fetched, build_config(), FactCheckTrace(mode="best_accuracy")))


def _run_news_cases() -> list[dict[str, Any]]:
    long_text = (
        "The article reports a public institutional update with named officials, dates, "
        "and enough body text to be treated as a normal article. "
    ) * 8
    fake_hits = {
        "moon mission": [
            {
                "title": "NASA updates Artemis II moon mission schedule",
                "url": "https://www.reuters.com/science/space/nasa-updates-artemis-ii-moon-mission-schedule-2026-05-10/",
                "snippet": "Reuters reports the same Artemis II moon mission update from NASA.",
                "source_url": "https://www.reuters.com",
            },
            {
                "title": "AP covers NASA Artemis II moon mission update",
                "url": "https://apnews.com/article/nasa-artemis-ii-moon-mission-update-2026",
                "snippet": "AP covers NASA's Artemis II moon mission update.",
                "source_url": "https://apnews.com",
            },
            {
                "title": "BBC reports NASA Artemis II moon mission update",
                "url": "https://www.bbc.com/news/articles/nasa-artemis-ii-moon-mission-update",
                "snippet": "BBC reports the same NASA Artemis II moon mission update.",
                "source_url": "https://www.bbc.com",
            },
        ],
        "climate data": [
            {
                "title": "NOAA publishes climate data update",
                "url": "https://www.reuters.com/sustainability/climate/noaa-publishes-climate-data-update-2026-05-13/",
                "snippet": "Reuters covers the same NOAA climate data update.",
                "source_url": "https://www.reuters.com",
            },
            {
                "title": "AP covers NOAA climate data update",
                "url": "https://apnews.com/article/noaa-climate-data-update-2026",
                "snippet": "AP covers the same NOAA climate data update.",
                "source_url": "https://apnews.com",
            },
            {
                "title": "BBC reports NOAA climate data update",
                "url": "https://www.bbc.com/news/articles/noaa-climate-data-update",
                "snippet": "BBC reports the same climate data update.",
                "source_url": "https://www.bbc.com",
            },
        ],
        "central bank": [
            {
                "title": "Central bank publishes rate decision",
                "url": "https://www.reuters.com/markets/rates/central-bank-publishes-rate-decision-2026-05-11/",
                "snippet": "Reuters covers the same central bank rate decision.",
                "source_url": "https://www.reuters.com",
            }
        ],
        "health alert": [
            {
                "title": "WHO issues health alert for travellers",
                "url": "https://www.reuters.com/world/who-issues-health-alert-travellers-2026-05-12/",
                "snippet": "Reuters covers the same WHO health alert.",
                "source_url": "https://www.reuters.com",
            },
            {
                "title": "AP covers WHO health alert for travellers",
                "url": "https://apnews.com/article/who-health-alert-travellers-2026",
                "snippet": "AP covers the same WHO health alert.",
                "source_url": "https://apnews.com",
            },
        ],
        "food safety": [
            {
                "title": "FDA announces food safety recall update",
                "url": "https://www.reuters.com/business/healthcare-pharmaceuticals/fda-announces-food-safety-recall-update-2026-05-14/",
                "snippet": "Reuters covers the same FDA food safety recall update.",
                "source_url": "https://www.reuters.com",
            },
            {
                "title": "AP covers FDA food safety recall update",
                "url": "https://apnews.com/article/fda-food-safety-recall-update-2026",
                "snippet": "AP covers the same recall update.",
                "source_url": "https://apnews.com",
            },
        ],
    }
    cases = [
        (
            "news_primary_high_with_corroboration",
            "https://www.reuters.com/science/space/nasa-updates-artemis-ii-moon-mission-schedule-2026-05-10/",
            {
                "url": "https://www.reuters.com/science/space/nasa-updates-artemis-ii-moon-mission-schedule-2026-05-10/",
                "title": "NASA updates Artemis II moon mission schedule",
                "text": long_text,
                "published_at": "2026-05-10",
                "author": "Reuters",
                "fetch_source": "direct",
            },
            fake_hits,
            _check_credibility_label("high"),
        ),
        (
            "news_primary_climate_high_with_corroboration",
            "https://www.reuters.com/sustainability/climate/noaa-publishes-climate-data-update-2026-05-13/",
            {
                "url": "https://www.reuters.com/sustainability/climate/noaa-publishes-climate-data-update-2026-05-13/",
                "title": "NOAA publishes climate data update",
                "text": long_text,
                "published_at": "2026-05-13",
                "author": "Reuters",
                "fetch_source": "direct",
            },
            fake_hits,
            _check_credibility_label("high"),
        ),
        (
            "news_institutional_high_without_corroboration",
            "https://www.nasa.gov/news-release/artemis-ii-crew-moon-mission-update",
            {
                "url": "https://www.nasa.gov/news-release/artemis-ii-crew-moon-mission-update",
                "title": "NASA updates Artemis II crew moon mission",
                "text": long_text,
                "published_at": "2026-05-10",
                "author": "NASA",
                "fetch_source": "direct",
            },
            {},
            _check_credibility_label("high"),
        ),
        (
            "news_primary_medium_without_corroboration",
            "https://apnews.com/article/central-bank-publishes-rate-decision-analysis-2026",
            {
                "url": "https://apnews.com/article/central-bank-publishes-rate-decision-analysis-2026",
                "title": "Central bank publishes rate decision analysis",
                "text": long_text,
                "published_at": "2026-05-11",
                "author": "Associated Press",
                "fetch_source": "direct",
            },
            {},
            _check_credibility_label("medium"),
        ),
        (
            "news_major_news_medium_without_corroboration",
            "https://www.bbc.com/news/articles/central-bank-rate-decision-analysis",
            {
                "url": "https://www.bbc.com/news/articles/central-bank-rate-decision-analysis",
                "title": "Central bank publishes rate decision analysis",
                "text": long_text,
                "published_at": "2026-05-11",
                "author": "BBC News",
                "fetch_source": "direct",
            },
            {},
            _check_credibility_label("medium"),
        ),
        (
            "news_institutional_health_high_with_matches",
            "https://www.who.int/news/item/12-05-2026-health-alert-for-travellers",
            {
                "url": "https://www.who.int/news/item/12-05-2026-health-alert-for-travellers",
                "title": "WHO issues health alert for travellers",
                "text": long_text,
                "published_at": "2026-05-12",
                "author": "WHO",
                "fetch_source": "direct",
            },
            fake_hits,
            _check_credibility_label("high"),
        ),
        (
            "news_major_listing_guardrail",
            "https://www.bbc.com/news",
            {
                "url": "https://www.bbc.com/news",
                "title": "BBC News",
                "text": "A news index page with many links and no single checkable article body.",
                "published_at": "",
                "author": "",
                "fetch_source": "direct",
            },
            {},
            _check_credibility_label("low", "unknown"),
        ),
        (
            "news_social_guardrail",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": "Viral video claim",
                "text": "A social video page is not enough evidence for a news credibility verdict.",
                "published_at": "",
                "author": "",
                "fetch_source": "direct",
            },
            {},
            _check_credibility_label("unknown"),
        ),
        (
            "news_low_trust_guardrail",
            "https://medium.com/example/shocking-secret-cure-exposed-world-news-claim",
            {
                "url": "https://medium.com/example/shocking-secret-cure-exposed-world-news-claim",
                "title": "Shocking secret cure exposed",
                "text": "A short viral post makes a sensational claim without named sources.",
                "published_at": "",
                "author": "",
                "fetch_source": "direct",
            },
            {},
            _check_credibility_label("unknown", "low"),
        ),
        (
            "news_unknown_source_without_matches",
            "https://example-blog.invalid/viral/shocking-secret-cure-world-news-claim",
            {
                "url": "https://example-blog.invalid/viral/shocking-secret-cure-world-news-claim",
                "title": "Shocking secret cure exposed",
                "text": "A short viral post makes a sensational claim without named sources.",
                "published_at": "",
                "author": "",
                "fetch_source": "direct",
            },
            {},
            _check_credibility_label("unknown", "low"),
        ),
        (
            "news_unknown_source_with_two_matches",
            "https://example.com/news/world/nasa-artemis-ii-moon-mission-update",
            {
                "url": "https://example.com/news/world/nasa-artemis-ii-moon-mission-update",
                "title": "NASA updates Artemis II moon mission schedule",
                "text": long_text,
                "published_at": "2026-05-10",
                "author": "Example Staff",
                "fetch_source": "direct",
            },
            fake_hits,
            _check_credibility_label("medium", "high"),
        ),
        (
            "news_unknown_source_with_three_matches",
            "https://example.com/news/world/noaa-climate-data-update",
            {
                "url": "https://example.com/news/world/noaa-climate-data-update",
                "title": "NOAA publishes climate data update",
                "text": long_text,
                "published_at": "2026-05-13",
                "author": "Example Staff",
                "fetch_source": "direct",
            },
            fake_hits,
            _check_credibility_label("medium", "high"),
        ),
        (
            "news_institutional_fda_high_with_matches",
            "https://www.fda.gov/news-events/press-announcements/fda-announces-food-safety-recall-update",
            {
                "url": "https://www.fda.gov/news-events/press-announcements/fda-announces-food-safety-recall-update",
                "title": "FDA announces food safety recall update",
                "text": long_text,
                "published_at": "2026-05-14",
                "author": "FDA",
                "fetch_source": "direct",
            },
            fake_hits,
            _check_credibility_label("high"),
        ),
        (
            "news_institutional_eac_high_without_matches",
            "https://www.eac.gov/news/2026/05/election-commission-publishes-voter-guidance-update",
            {
                "url": "https://www.eac.gov/news/2026/05/election-commission-publishes-voter-guidance-update",
                "title": "Election commission publishes voter guidance update",
                "text": long_text,
                "published_at": "2026-05-15",
                "author": "Election Assistance Commission",
                "fetch_source": "direct",
            },
            {},
            _check_credibility_label("high"),
        ),
        (
            "news_social_reddit_guardrail",
            "https://www.reddit.com/r/news/comments/example/viral_claim/",
            {
                "url": "https://www.reddit.com/r/news/comments/example/viral_claim/",
                "title": "Viral claim thread",
                "text": "A social discussion thread is not enough evidence for a news credibility verdict.",
                "published_at": "",
                "author": "",
                "fetch_source": "direct",
            },
            {},
            _check_credibility_label("unknown"),
        ),
    ]
    rows: list[dict[str, Any]] = []
    for case_id, url, fetched, search_hits, checker in cases:
        payload = _news_payload(fetched["text"], url, fetched, search_hits)
        passed, detail = checker(payload)
        credibility = payload.get("credibility") or {}
        rows.append(
            {
                "id": case_id,
                "section": "news",
                "input": url,
                "passed": passed,
                "detail": detail,
                "verdict": payload.get("verdict"),
                "confidence": payload.get("confidence"),
                "credibility_label": credibility.get("label"),
                "credibility_score": credibility.get("score"),
                "summary": payload.get("summary"),
            }
        )
    return rows


def _text_image(text: str, *, width: int = 1200, height: int = 320) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font = None
    for candidate in (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/calibri.ttf")):
        if candidate.exists():
            font = ImageFont.truetype(str(candidate), 44)
            break
    if font is None:
        font = ImageFont.load_default()
    draw.multiline_text((48, 80), text, fill="black", font=font, spacing=18)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _blank_image() -> bytes:
    image = Image.new("RGB", (600, 300), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _run_screenshot_cases() -> list[dict[str, Any]]:
    cases = [
        (
            "screenshot_ocr_fake_claim",
            _text_image("Elephants are insects."),
            "",
            _check_verdict("fake"),
        ),
        (
            "screenshot_ocr_true_claim",
            _text_image("The capital of France is Paris."),
            "",
            _check_verdict("true"),
        ),
        (
            "screenshot_ocr_arithmetic_false",
            _text_image("2 plus 2 equals 5"),
            "",
            _check_verdict("fake"),
        ),
        (
            "screenshot_ocr_sky_false",
            _text_image("The sky is green."),
            "",
            _check_verdict("fake"),
        ),
        (
            "screenshot_ocr_moon_false",
            _text_image("The Moon is made of cheese."),
            "",
            _check_verdict("fake"),
        ),
        (
            "screenshot_ocr_banana_true",
            _text_image("Bananas are yellow."),
            "",
            _check_verdict("true"),
        ),
        (
            "screenshot_question_overrides_ocr",
            _text_image("Noisy screenshot text: Joe Biden is president."),
            "Elephants are mammals.",
            _check_verdict("true"),
        ),
        (
            "screenshot_question_override_fake",
            _text_image("Noisy screenshot text: Elephants are mammals."),
            "Elephants are insects.",
            _check_verdict("fake"),
        ),
        (
            "screenshot_blank_abstains",
            _blank_image(),
            "",
            _check_verdict("uncertain"),
        ),
        (
            "screenshot_ocr_dog_true",
            _text_image("Dogs are mammals."),
            "",
            _check_verdict("true"),
        ),
        (
            "screenshot_ocr_cat_plant_false",
            _text_image("Cats are plants."),
            "",
            _check_verdict("fake"),
        ),
        (
            "screenshot_ocr_numeric_true",
            _text_image("100 is lower than 200"),
            "",
            _check_verdict("true"),
        ),
    ]
    rows: list[dict[str, Any]] = []
    for case_id, image_bytes, question, checker in cases:
        payload = _public(run_screenshot_factcheck(image_bytes, filename=f"{case_id}.png", question=question))
        passed, detail = checker(payload)
        image_analysis = payload.get("image_analysis") or {}
        rows.append(
            {
                "id": case_id,
                "section": "screenshots",
                "input": question or "generated screenshot",
                "passed": passed,
                "detail": detail,
                "verdict": payload.get("verdict"),
                "confidence": payload.get("confidence"),
                "ocr_confidence": image_analysis.get("ocr_confidence"),
                "summary": payload.get("summary"),
            }
        )
    return rows


def _ai_png_with_metadata() -> bytes:
    return _ai_png_with_marker("Stable Diffusion / ComfyUI", (180, 120, 210))


def _ai_png_with_marker(marker: str, color: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (768, 768), color)
    draw = ImageDraw.Draw(image)
    draw.ellipse((180, 180, 590, 590), fill=(245, 220, 170))
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("Software", marker)
    output = BytesIO()
    image.save(output, format="PNG", pnginfo=metadata)
    return output.getvalue()


def _plain_jpeg() -> bytes:
    image = Image.new("RGB", (900, 600), (80, 140, 180))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 220, 820, 420), fill=(230, 230, 210))
    draw.line((80, 420, 820, 220), fill=(60, 80, 100), width=8)
    output = BytesIO()
    image.save(output, format="JPEG", quality=92)
    return output.getvalue()


def _square_png_without_metadata() -> bytes:
    image = Image.new("RGB", (1024, 1024), (150, 170, 190))
    draw = ImageDraw.Draw(image)
    draw.rectangle((180, 240, 850, 780), fill=(210, 220, 225))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _jpeg_with_camera_metadata() -> bytes:
    image = Image.new("RGB", (1200, 800), (110, 150, 110))
    draw = ImageDraw.Draw(image)
    draw.rectangle((120, 300, 1080, 620), fill=(210, 210, 190))
    exif = Image.Exif()
    exif[271] = "Canon"
    exif[272] = "EOS Demo"
    output = BytesIO()
    image.save(output, format="JPEG", quality=90, exif=exif)
    return output.getvalue()


def _run_image_cases() -> list[dict[str, Any]]:
    cases = [
        ("image_ai_metadata_marker", _ai_png_with_metadata(), "metadata_ai.png", _check_ai_label("likely_ai")),
        (
            "image_midjourney_metadata_marker",
            _ai_png_with_marker("Midjourney synthetic image", (120, 180, 210)),
            "midjourney_metadata.png",
            _check_ai_label("likely_ai"),
        ),
        (
            "image_dalle_metadata_marker",
            _ai_png_with_marker("DALL-E generated asset", (180, 210, 140)),
            "dalle_metadata.png",
            _check_ai_label("likely_ai"),
        ),
        (
            "image_firefly_metadata_marker",
            _ai_png_with_marker("Adobe Firefly generated image", (210, 160, 120)),
            "firefly_metadata.png",
            _check_ai_label("likely_ai"),
        ),
        (
            "image_ideogram_metadata_marker",
            _ai_png_with_marker("Ideogram synthetic poster", (150, 110, 210)),
            "ideogram_metadata.png",
            _check_ai_label("likely_ai"),
        ),
        ("image_plain_jpeg_no_false_ai", _plain_jpeg(), "plain_photo.jpg", _check_ai_label("uncertain", "likely_not_ai")),
        (
            "image_square_no_metadata_no_false_ai",
            _square_png_without_metadata(),
            "square_plain.png",
            _check_ai_label("uncertain", "likely_not_ai"),
        ),
        (
            "image_camera_metadata_not_proof_of_real",
            _jpeg_with_camera_metadata(),
            "camera_metadata.jpg",
            _check_ai_label("uncertain", "likely_not_ai"),
        ),
        (
            "image_leonardo_metadata_marker",
            _ai_png_with_marker("Leonardo AI generated scene", (130, 170, 220)),
            "leonardo_metadata.png",
            _check_ai_label("likely_ai"),
        ),
        (
            "image_automatic1111_metadata_marker",
            _ai_png_with_marker("AUTOMATIC1111 stable diffusion output", (120, 120, 150)),
            "automatic1111_metadata.png",
            _check_ai_label("likely_ai"),
        ),
        (
            "image_second_plain_jpeg_no_false_ai",
            _plain_jpeg(),
            "plain_photo_second.jpg",
            _check_ai_label("uncertain", "likely_not_ai"),
        ),
    ]
    rows: list[dict[str, Any]] = []
    for case_id, image_bytes, filename, checker in cases:
        payload = _public(run_ai_image_check(image_bytes, filename=filename))
        passed, detail = checker(payload)
        image_analysis = payload.get("image_analysis") or {}
        rows.append(
            {
                "id": case_id,
                "section": "images",
                "input": filename,
                "passed": passed,
                "detail": detail,
                "verdict": payload.get("verdict"),
                "confidence": payload.get("confidence"),
                "ai_label": image_analysis.get("ai_label"),
                "ai_generated_score": image_analysis.get("ai_generated_score"),
                "summary": payload.get("summary"),
            }
        )
    return rows


def _run_api_contract_cases() -> list[dict[str, Any]]:
    from fastapi.testclient import TestClient

    from src.api_factcheck import app

    def response_row(case_id: str, response: Any, checker: CaseCheck) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text}
        passed, detail = checker(payload)
        status_ok = response.status_code < 400
        return {
            "id": case_id,
            "section": "api_contract",
            "input": f"{response.request.method} {response.request.url.path}",
            "passed": status_ok and passed,
            "detail": f"status_code={response.status_code}; {detail}",
            "verdict": payload.get("verdict"),
            "confidence": payload.get("confidence"),
            "summary": payload.get("summary") or payload.get("status"),
        }

    rows: list[dict[str, Any]] = []
    with TestClient(app) as client:
        rows.append(response_row("api_health_ok", client.get("/health"), _check_status("ok")))
        rows.append(response_row("api_ready_ok", client.get("/ready"), _check_status("ready")))

        cors_response = client.options(
            "/factcheck",
            headers={
                "origin": "https://verity-lens.example",
                "access-control-request-method": "POST",
            },
        )
        cors_payload = {
            "status": "ok" if cors_response.headers.get("access-control-allow-origin") == "*" else "bad",
            "methods": cors_response.headers.get("access-control-allow-methods", ""),
        }
        cors_passed, cors_detail = _check_status("ok")(cors_payload)
        rows.append(
            {
                "id": "api_cors_preflight_ok",
                "section": "api_contract",
                "input": "OPTIONS /factcheck",
                "passed": cors_response.status_code == 200 and cors_passed and "POST" in cors_payload["methods"],
                "detail": f"status_code={cors_response.status_code}; {cors_detail}; methods={cors_payload['methods']}",
                "summary": "CORS preflight for Flutter Web/mobile gateway",
            }
        )

        rows.append(
            response_row(
                "api_factcheck_true",
                client.post("/factcheck", json={"text": "Elephants are mammals."}),
                _check_verdict("true"),
            )
        )
        rows.append(
            response_row(
                "api_factcheck_fake",
                client.post("/factcheck", json={"text": "Elephants are insects."}),
                _check_verdict("fake"),
            )
        )
        rows.append(
            response_row(
                "api_screenshot_fake",
                client.post(
                    "/factcheck-image",
                    data={"analysis_type": "screenshot", "question": ""},
                    files={"image_file": ("claim.png", _text_image("2 plus 2 equals 5"), "image/png")},
                ),
                _check_verdict("fake"),
            )
        )
        rows.append(
            response_row(
                "api_ai_image_metadata",
                client.post(
                    "/factcheck-image",
                    data={"analysis_type": "ai_image", "question": ""},
                    files={"image_file": ("metadata_ai.png", _ai_png_with_metadata(), "image/png")},
                ),
                _check_ai_label("likely_ai"),
            )
        )
        empty_payload_response = client.post("/factcheck", json={})
        rows.append(
            {
                "id": "api_factcheck_empty_rejected",
                "section": "api_contract",
                "input": "POST /factcheck",
                "passed": empty_payload_response.status_code == 400,
                "detail": f"status_code={empty_payload_response.status_code}; expected 400 for missing text/url",
                "summary": "Rejects empty fact-check requests",
            }
        )
        invalid_analysis_response = client.post(
            "/factcheck-image",
            data={"analysis_type": "bogus", "question": ""},
            files={"image_file": ("metadata_ai.png", _ai_png_with_metadata(), "image/png")},
        )
        rows.append(
            {
                "id": "api_image_invalid_analysis_rejected",
                "section": "api_contract",
                "input": "POST /factcheck-image",
                "passed": invalid_analysis_response.status_code == 400,
                "detail": f"status_code={invalid_analysis_response.status_code}; expected 400 for invalid analysis_type",
                "summary": "Rejects unsupported image analysis modes",
            }
        )
        missing_image_response = client.post(
            "/factcheck-image",
            data={"analysis_type": "screenshot", "question": ""},
        )
        rows.append(
            {
                "id": "api_image_missing_file_rejected",
                "section": "api_contract",
                "input": "POST /factcheck-image",
                "passed": missing_image_response.status_code >= 400,
                "detail": f"status_code={missing_image_response.status_code}; expected client error for missing image_file",
                "summary": "Rejects image analysis requests without an uploaded file",
            }
        )
        unsupported_method_response = client.get("/factcheck")
        rows.append(
            {
                "id": "api_factcheck_get_method_rejected",
                "section": "api_contract",
                "input": "GET /factcheck",
                "passed": unsupported_method_response.status_code == 405,
                "detail": f"status_code={unsupported_method_response.status_code}; expected 405 for unsupported method",
                "summary": "Rejects unsupported GET method on factcheck endpoint",
            }
        )

    return rows


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sections: dict[str, dict[str, Any]] = {}
    for row in rows:
        section = row["section"]
        bucket = sections.setdefault(section, {"total": 0, "passed": 0, "failed": 0, "pass_rate": 0.0})
        bucket["total"] += 1
        if row["passed"]:
            bucket["passed"] += 1
        else:
            bucket["failed"] += 1
    for bucket in sections.values():
        bucket["pass_rate"] = bucket["passed"] / max(bucket["total"], 1)
    total = len(rows)
    passed = sum(1 for row in rows if row["passed"])
    return {
        "created_at": _now_iso(),
        "target_pass_rate": TARGET_PASS_RATE,
        "min_cases_per_section": MIN_CASES_PER_SECTION,
        "min_cases_by_section": MIN_CASES_BY_SECTION,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": passed / max(total, 1),
        "gate_passed": all(
            bucket["pass_rate"] >= TARGET_PASS_RATE and bucket["total"] >= _min_cases_for_section(section)
            for section, bucket in sections.items()
        ),
        "sections": sections,
    }


def _write_markdown(payload: dict[str, Any], path: Path) -> None:
    summary = payload["summary"]
    lines = [
        "# Product Acceptance Report",
        "",
        f"- Created: `{summary['created_at']}`",
        "- Scope: facts, news credibility, screenshot OCR, AI-image risk, API/mobile contract",
        f"- Target pass rate: `{_pct(summary['target_pass_rate'])}`",
        f"- Default minimum cases per section: `{summary['min_cases_per_section']}`",
        f"- Overall: `{summary['passed']}/{summary['total']}` = `{_pct(summary['pass_rate'])}`",
        f"- Gate: `{'passed' if summary['gate_passed'] else 'failed'}`",
        "",
        "## Section Results",
        "",
        "| Section | Passed | Total | Minimum | Rate | Gate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for section, bucket in sorted(summary["sections"].items()):
        min_cases = int((summary.get("min_cases_by_section") or {}).get(section, summary["min_cases_per_section"]))
        gate = bucket["pass_rate"] >= summary["target_pass_rate"] and bucket["total"] >= min_cases
        lines.append(
            f"| {section} | {bucket['passed']} | {bucket['total']} | {min_cases} | {_pct(bucket['pass_rate'])} | {'yes' if gate else 'no'} |"
        )
    lines.extend(["", "## Cases", "", "| ID | Section | Pass | Detail |", "|---|---|---:|---|"])
    for row in payload["cases"]:
        lines.append(
            "| {id} | {section} | {passed} | {detail} |".format(
                id=row["id"],
                section=row["section"],
                passed="yes" if row["passed"] else "no",
                detail=str(row["detail"]).replace("|", "\\|"),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    rows: list[dict[str, Any]] = []
    rows.extend(_run_fact_cases())
    rows.extend(_run_news_cases())
    rows.extend(_run_screenshot_cases())
    rows.extend(_run_image_cases())
    rows.extend(_run_api_contract_cases())
    payload = {"summary": _summarize(rows), "cases": rows}

    DEFAULT_OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(payload, DEFAULT_OUT_MD)

    summary = payload["summary"]
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["gate_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
