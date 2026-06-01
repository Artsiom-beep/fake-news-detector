from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from factcheck.config import build_config
from factcheck.service import run_factcheck


def _case(case_id: str, text: str, expected: str, category: str, language: str = "en") -> dict[str, str]:
    return {
        "id": case_id,
        "text": text,
        "expected": expected,
        "category": category,
        "language": language,
    }


def build_cases() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []

    everyday = [
        ("cars_have_wheels", "Cars have wheels", "true"),
        ("cars_have_no_wheels", "Cars have no wheels", "fake"),
        ("cars_are_alive", "Cars are alive", "fake"),
        ("bicycles_have_wheels", "Bicycles have wheels", "true"),
        ("bicycles_have_engines", "Bicycles have engines", "fake"),
        ("airplanes_can_fly", "Airplanes can fly", "true"),
        ("boats_can_fly", "Boats can fly", "fake"),
        ("chairs_are_furniture", "Chairs are furniture", "true"),
        ("chairs_are_food", "Chairs are food", "fake"),
        ("tables_are_animals", "Tables are animals", "fake"),
        ("phones_are_electronic", "Phones are electronic", "true"),
        ("phones_are_mammals", "Phones are mammals", "fake"),
        ("computers_are_devices", "Computers are devices", "true"),
        ("computers_are_alive", "Computers are alive", "fake"),
        ("refrigerators_are_cold", "Refrigerators are cold", "true"),
        ("ovens_are_cold", "Ovens are cold", "fake"),
        ("knives_are_sharp", "Knives are sharp", "true"),
        ("forks_are_animals", "Forks are animals", "fake"),
        ("spoons_are_tools", "Spoons are tools", "true"),
        ("rocks_are_food", "Rocks are food", "fake"),
        ("water_is_liquid", "Water is liquid", "true"),
        ("water_is_dry", "Water is dry", "fake"),
        ("ice_is_solid", "Ice is solid", "true"),
        ("ice_is_hot", "Ice is hot", "fake"),
        ("fire_is_hot", "Fire is hot", "true"),
        ("snow_is_black", "Snow is black", "fake"),
    ]
    for index, (name, text, expected) in enumerate(everyday, start=1):
        cases.append(_case(f"everyday_{index:03d}_{name}", text, expected, "everyday_objects"))

    food_and_materials = [
        ("apple_fruit", "Apples are fruit", "true"),
        ("apple_blue", "Apples are blue", "fake"),
        ("banana_yellow", "Bananas are yellow", "true"),
        ("banana_poisonous", "Bananas are poisonous", "fake"),
        ("cucumber_edible", "Cucumbers are edible", "true"),
        ("cucumber_poisonous", "Cucumbers are poisonous", "fake"),
        ("lemon_sour", "Lemons are sour", "true"),
        ("lemon_sweet", "Lemons are sweet", "fake"),
        ("salt_salty", "Salt is salty", "true"),
        ("salt_sweet", "Salt is sweet", "fake"),
        ("sugar_sweet", "Sugar is sweet", "true"),
        ("sugar_salty", "Sugar is salty", "fake"),
        ("milk_liquid", "Milk is liquid", "true"),
        ("milk_black", "Milk is black", "fake"),
        ("coffee_liquid", "Coffee is liquid", "true"),
        ("coffee_blue", "Coffee is blue", "fake"),
        ("wood_gas", "Wood is a gas", "fake"),
        ("plastic_animal", "Plastic is an animal", "fake"),
        ("glass_food", "Glass is food", "fake"),
        ("glass_transparent_material", "Glass is transparent", "true"),
        ("air_solid", "Air is solid", "fake"),
        ("steam_hot", "Steam is hot", "true"),
        ("boats_float", "Boats can float", "true"),
        ("boats_plants", "Boats are plants", "fake"),
        ("plants_need_water", "Plants need water", "true"),
        ("plants_fly", "Plants can fly", "fake"),
        ("trees_plants", "Trees are plants", "true"),
        ("trees_animals", "Trees are animals", "fake"),
        ("flowers_plants", "Flowers are plants", "true"),
        ("roses_flowers", "Roses are flowers", "true"),
        ("roses_fish", "Roses are fish", "fake"),
        ("rocks_alive", "Rocks are alive", "fake"),
    ]
    for index, (name, text, expected) in enumerate(food_and_materials, start=1):
        cases.append(_case(f"food_material_{index:03d}_{name}", text, expected, "food_and_materials"))

    biology = [
        ("humans_drink_water", "Humans can drink water", "true"),
        ("humans_have_wings", "Humans have wings", "fake"),
        ("humans_no_wings", "Humans do not have wings", "true"),
        ("dogs_mammals", "Dogs are mammals", "true"),
        ("dogs_plants", "Dogs are plants", "fake"),
        ("cats_animals", "Cats are animals", "true"),
        ("cats_can_fly", "Cats can fly", "fake"),
        ("cows_eat_grass", "Cows eat grass", "true"),
        ("cows_can_fly", "Cows can fly", "fake"),
        ("horses_mammals", "Horses are mammals", "true"),
        ("horses_have_wheels", "Horses have wheels", "fake"),
        ("pigs_birds", "Pigs are birds", "fake"),
        ("chickens_lay_eggs", "Chickens lay eggs", "true"),
        ("ducks_swim", "Ducks can swim", "true"),
        ("penguins_fly", "Penguins can fly", "fake"),
        ("bats_fly", "Bats can fly", "true"),
        ("bats_birds", "Bats are birds", "fake"),
        ("whales_mammals", "Whales are mammals", "true"),
        ("whales_fish", "Whales are fish", "fake"),
        ("dolphins_fish", "Dolphins are fish", "fake"),
        ("sharks_fish", "Sharks are fish", "true"),
        ("spiders_animals", "Spiders are animals", "true"),
        ("spiders_insects", "Spiders are insects", "fake"),
        ("bees_insects", "Bees are insects", "true"),
        ("ants_mammals", "Ants are mammals", "fake"),
        ("snakes_have_legs", "Snakes have legs", "fake"),
        ("turtles_reptiles", "Turtles are reptiles", "true"),
        ("frogs_fly", "Frogs can fly", "fake"),
        ("toads_jump", "Toads can jump", "true"),
        ("fish_water", "Fish live in water", "true"),
        ("fish_fly", "Fish can fly", "fake"),
    ]
    for index, (name, text, expected) in enumerate(biology, start=1):
        cases.append(_case(f"biology_{index:03d}_{name}", text, expected, "biology"))

    science = [
        ("oxygen_gas", "Oxygen is a gas", "true"),
        ("oxygen_metal", "Oxygen is a metal", "fake"),
        ("helium_gas", "Helium is a gas", "true"),
        ("iron_metal", "Iron is a metal", "true"),
        ("iron_gas", "Iron is a gas", "fake"),
        ("gold_metal", "Gold is a metal", "true"),
        ("gold_liquid", "Gold is a liquid", "fake"),
        ("air_gas", "Air is a gas", "true"),
        ("air_food", "Air is food", "fake"),
        ("steam_gas", "Steam is a gas", "true"),
        ("steam_ice", "Steam is ice", "fake"),
        ("wood_solid", "Wood is solid", "true"),
        ("plastic_alive", "Plastic is alive", "fake"),
        ("glass_transparent", "Glass is transparent", "true"),
        ("mars_planet", "Mars is a planet", "true"),
        ("mars_star", "Mars is a star", "fake"),
        ("earth_planet", "Earth is a planet", "true"),
        ("sun_planet", "The sun is a planet", "fake"),
        ("moon_cheese", "The moon is made of cheese", "fake"),
        ("week_days", "A week has seven days", "true"),
        ("week_ten_days", "A week has ten days", "fake"),
        ("year_months", "A year has twelve months", "true"),
        ("year_week", "A year has seven days", "fake"),
    ]
    for index, (name, text, expected) in enumerate(science, start=1):
        cases.append(_case(f"science_{index:03d}_{name}", text, expected, "science"))

    geography = [
        ("france_paris", "The capital of France is Paris", "true"),
        ("france_berlin", "The capital of France is Berlin", "fake"),
        ("germany_berlin", "The capital of Germany is Berlin", "true"),
        ("germany_paris", "The capital of Germany is Paris", "fake"),
        ("poland_warsaw", "The capital of Poland is Warsaw", "true"),
        ("poland_krakow", "The capital of Poland is Krakow", "fake"),
        ("italy_rome", "The capital of Italy is Rome", "true"),
        ("italy_milan", "The capital of Italy is Milan", "fake"),
        ("spain_madrid", "The capital of Spain is Madrid", "true"),
        ("spain_barcelona", "The capital of Spain is Barcelona", "fake"),
        ("portugal_lisbon", "The capital of Portugal is Lisbon", "true"),
        ("ukraine_kyiv", "The capital of Ukraine is Kyiv", "true"),
        ("paris_france", "Paris is the capital of France", "true"),
        ("berlin_france", "Berlin is the capital of France", "fake"),
    ]
    for index, (name, text, expected) in enumerate(geography, start=1):
        cases.append(_case(f"geo_{index:03d}_{name}", text, expected, "geography"))

    multilingual = [
        ("ru_cars_wheels", "Машины имеют колеса", "true", "ru"),
        ("ru_humans_wings", "Люди имеют крылья", "fake", "ru"),
        ("ru_frogs_fly", "Лягушки умеют летать", "fake", "ru"),
        ("ru_cows_grass", "Коровы едят траву", "true", "ru"),
        ("ru_oxygen_gas", "Кислород это газ", "true", "ru"),
        ("ru_iron_gas", "Железо это газ", "fake", "ru"),
        ("ru_week_days", "Неделя имеет семь дней", "true", "ru"),
        ("ru_bananas_yellow", "Бананы желтые", "true", "ru"),
        ("ru_milk_black", "Молоко черное", "fake", "ru"),
        ("ru_salt_sweet", "Соль сладкая", "fake", "ru"),
        ("ru_snakes_legs", "Змеи имеют ноги", "fake", "ru"),
        ("ru_penguins_fly", "Пингвины умеют летать", "fake", "ru"),
        ("pl_cars_wheels", "Samochody mają koła", "true", "pl"),
        ("pl_humans_wings", "Ludzie mają skrzydła", "fake", "pl"),
        ("pl_spiders_insects", "Pająki są owadami", "fake", "pl"),
        ("pl_oxygen_gas", "Tlen jest gaz", "true", "pl"),
        ("pl_week_days", "Tydzień ma siedem dni", "true", "pl"),
        ("pl_bananas_yellow", "Banany są żółte", "true", "pl"),
        ("pl_salt_sweet", "Sól jest słodka", "fake", "pl"),
        ("pl_penguins_fly", "Pingwiny mogą latać", "fake", "pl"),
        ("pl_trees_plants", "Drzewa są roślinami", "true", "pl"),
        ("es_cars_wheels", "Los coches tienen ruedas", "true", "es"),
        ("es_humans_wings", "Los humanos tienen alas", "fake", "es"),
        ("es_spiders_insects", "Las arañas son insectos", "fake", "es"),
        ("es_whales_fish", "Las ballenas son peces", "fake", "es"),
        ("es_bananas_yellow", "Los plátanos son amarillos", "true", "es"),
        ("es_salt_sweet", "La sal es dulce", "fake", "es"),
        ("fr_cars_wheels", "Les voitures ont des roues", "true", "fr"),
        ("fr_humans_wings", "Les humains ont des ailes", "fake", "fr"),
        ("fr_spiders_insects", "Les araignées sont des insectes", "fake", "fr"),
        ("fr_whales_fish", "Les baleines sont des poissons", "fake", "fr"),
        ("fr_bananas_yellow", "Les bananes sont jaunes", "true", "fr"),
        ("fr_salt_sweet", "Le sel est sucré", "fake", "fr"),
        ("de_cars_wheels", "Autos haben Räder", "true", "de"),
        ("de_humans_wings", "Menschen haben Flügel", "fake", "de"),
        ("de_spiders_insects", "Spinnen sind Insekten", "fake", "de"),
        ("de_whales_fish", "Wale sind Fische", "fake", "de"),
        ("de_bananas_yellow", "Bananen sind gelb", "true", "de"),
        ("de_salt_sweet", "Salz ist süß", "fake", "de"),
    ]
    for index, (name, text, expected, language) in enumerate(multilingual, start=1):
        cases.append(_case(f"multi_{index:03d}_{name}", text, expected, "multilingual", language))

    unknown = [
        "Apple is expensive",
        "Cars are lucky",
        "Dogs are happy",
        "Coffee cures cancer",
        "Water prevents aging",
        "Iron cures headaches",
        "Phones are morally good",
        "Computers are trustworthy",
        "The moon is lucky",
        "Gold makes people shine in dreams",
        "Plastic cures flu",
        "A chair is politically neutral",
        "A tree is happier than a flower",
        "Zorbax is edible",
        "Flarnovia is a country",
        "Blorple is a metal",
        "The city of Narmia is real",
        "XQ-17 berries cure fever",
        "A secret forum post proves water is toxic",
        "An anonymous screenshot proves cats are robots",
        "This viral rumor is confirmed",
        "A newly discovered planet is made of sugar",
        "The unknown company Mirava owns the Moon",
        "A private source says Mars is wet today",
        "A rumor says dogs invented bicycles",
    ]
    for index, text in enumerate(unknown, start=1):
        cases.append(_case(f"unknown_{index:03d}", text, "uncertain", "unknown_or_insufficient"))

    subjective = [
        ("op_best_food", "Pizza is the best food", "en"),
        ("op_better_pet", "Cats are better than dogs", "en"),
        ("op_should_ban", "People should ban all cars", "en"),
        ("op_beautiful_city", "Paris is the most beautiful city", "en"),
        ("op_movie_good", "This movie is boring", "en"),
        ("op_ru_better", "Мне кажется, кофе лучше чая", "ru"),
        ("op_ru_best", "Пицца это лучшая еда", "ru"),
        ("op_ru_should", "Люди должны запретить машины", "ru"),
        ("op_pl_best", "Pizza jest najlepszym jedzeniem", "pl"),
        ("op_pl_opinion", "Moim zdaniem koty są lepsze niż psy", "pl"),
        ("op_pl_should", "Ludzie powinni zakazać samochodów", "pl"),
    ]
    for index, (name, text, language) in enumerate(subjective, start=1):
        cases.append(_case(f"subjective_{index:03d}_{name}", text, "uncertain", "subjective_take", language))

    arithmetic = [
        ("arith_2_2", "2 plus 2 equals 4", "true"),
        ("arith_2_5", "2 plus 2 equals 5", "fake"),
        ("arith_10_2", "10 divided by 2 equals 5", "true"),
        ("arith_10_3", "10 divided by 2 equals 3", "fake"),
        ("arith_100_200", "100 is lower than 200", "true"),
        ("arith_200_100", "100 is greater than 200", "fake"),
        ("arith_symbol_true", "20 >= 15", "true"),
        ("arith_symbol_false", "7 < 3", "fake"),
    ]
    for index, (name, text, expected) in enumerate(arithmetic, start=1):
        cases.append(_case(f"arith_{index:03d}_{name}", text, expected, "arithmetic"))

    return cases


def _evaluate_case(row: dict[str, str]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        payload = run_factcheck(text=row["text"]).to_public_dict()
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        evidence = payload.get("evidence", [])
        return {
            **row,
            "pred": payload.get("verdict", "uncertain"),
            "confidence": payload.get("confidence", 0.0),
            "summary": payload.get("summary", ""),
            "claim": payload.get("claim", ""),
            "evidence_count": len(evidence),
            "top_source_type": evidence[0].get("source_type", "") if evidence else "",
            "fallbacks_used": payload.get("trace", {}).get("fallbacks_used", []),
            "decision_reasons": payload.get("trace", {}).get("decision_reasons", []),
            "elapsed_ms": elapsed_ms,
            "ok": payload.get("verdict", "uncertain") == row["expected"],
        }
    except Exception as exc:
        return {
            **row,
            "pred": "error",
            "confidence": 0.0,
            "summary": "",
            "claim": "",
            "evidence_count": 0,
            "top_source_type": "",
            "fallbacks_used": [],
            "decision_reasons": [],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "ok": False,
            "error": str(exc),
        }


def _breakdown(details: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in details:
        grouped[str(item.get(key, "unknown"))].append(item)

    result: dict[str, Any] = {}
    for name, items in sorted(grouped.items()):
        predictions = Counter(str(item.get("pred", "unknown")) for item in items)
        result[name] = {
            "n": len(items),
            "accuracy": sum(1 for item in items if item.get("ok")) / max(len(items), 1),
            "predictions": dict(sorted(predictions.items())),
        }
    return result


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _markdown_report(payload: dict[str, Any]) -> str:
    failures = [item for item in payload["details"] if not item.get("ok")]
    lines = [
        "# Common Sense Big Eval",
        "",
        f"- Generated: `{payload['generated_at']}`",
        f"- Pipeline: `{payload['pipeline_version']}`",
        f"- Cases: `{payload['n']}`",
        f"- Accuracy: `{_pct(payload['accuracy'])}`",
        f"- Hard verdict precision: `{_pct(payload['hard_verdict_precision'])}`",
        f"- Expected-uncertain accuracy: `{_pct(payload['expected_uncertain_accuracy'])}`",
        f"- Error rate: `{_pct(payload['error_rate'])}`",
        "",
        "## Category Breakdown",
        "",
        "| Category | N | Accuracy | Predictions |",
        "|---|---:|---:|---|",
    ]
    for category, item in payload["by_category"].items():
        lines.append(
            f"| {category} | {item['n']} | {_pct(item['accuracy'])} | "
            f"`{json.dumps(item['predictions'], ensure_ascii=False, sort_keys=True)}` |"
        )

    lines.extend(["", "## Language Breakdown", "", "| Language | N | Accuracy | Predictions |", "|---|---:|---:|---|"])
    for language, item in payload["by_language"].items():
        lines.append(
            f"| {language} | {item['n']} | {_pct(item['accuracy'])} | "
            f"`{json.dumps(item['predictions'], ensure_ascii=False, sort_keys=True)}` |"
        )

    lines.extend(["", "## Failures", ""])
    if not failures:
        lines.append("No failures.")
    else:
        lines.append("| ID | Expected | Pred | Conf | Category | Text | Summary |")
        lines.append("|---|---|---|---:|---|---|---|")
        for item in failures[:80]:
            text = str(item.get("text", "")).replace("|", "\\|")
            summary = str(item.get("summary", "")).replace("|", "\\|")
            lines.append(
                f"| {item.get('id', '')} | {item.get('expected', '')} | {item.get('pred', '')} | "
                f"{float(item.get('confidence', 0.0)):.2f} | {item.get('category', '')} | {text} | {summary} |"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a large common-sense, unknown-claim, and take-abstention eval.")
    parser.add_argument("--json-out", default="outputs/factcheck_runs/common_sense_big_latest.json")
    parser.add_argument("--md-out", default="reports/common_sense_big_latest.md")
    args = parser.parse_args()

    rows = build_cases()
    details = [_evaluate_case(row) for row in rows]
    n = len(details)
    predictions = Counter(str(item.get("pred", "unknown")) for item in details)
    hard = [item for item in details if item.get("pred") in {"true", "fake"}]
    expected_uncertain = [item for item in details if item.get("expected") == "uncertain"]
    config = build_config()
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "pipeline_version": config.pipeline_version,
        "n": n,
        "accuracy": sum(1 for item in details if item.get("ok")) / max(n, 1),
        "hard_verdict_precision": sum(1 for item in hard if item.get("ok")) / max(len(hard), 1),
        "expected_uncertain_accuracy": sum(1 for item in expected_uncertain if item.get("ok")) / max(len(expected_uncertain), 1),
        "error_rate": predictions.get("error", 0) / max(n, 1),
        "predictions": dict(sorted(predictions.items())),
        "by_category": _breakdown(details, "category"),
        "by_language": _breakdown(details, "language"),
        "details": details,
    }

    json_out = ROOT / args.json_out
    md_out = ROOT / args.md_out
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_out.write_text(_markdown_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "n": payload["n"],
                "accuracy": round(payload["accuracy"], 4),
                "hard_verdict_precision": round(payload["hard_verdict_precision"], 4),
                "expected_uncertain_accuracy": round(payload["expected_uncertain_accuracy"], 4),
                "error_rate": round(payload["error_rate"], 4),
                "json_out": str(json_out),
                "md_out": str(md_out),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
