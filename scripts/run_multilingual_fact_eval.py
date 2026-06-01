from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from factcheck.service import run_factcheck
from factcheck.translation import normalize_fact_text


LANGUAGE_CASES: dict[str, list[tuple[str, str]]] = {
    "ru": [
        ("Люди могут пить воду", "true"),
        ("Люди не могут пить воду", "fake"),
        ("Кошки являются животными", "true"),
        ("Кошки являются растениями", "fake"),
        ("Собаки являются млекопитающими", "true"),
        ("Слоны являются насекомыми", "fake"),
        ("Трава является зеленой", "true"),
        ("Трава является фиолетовой", "fake"),
        ("Яблоки являются фруктами", "true"),
        ("Яблоки являются синими", "fake"),
        ("Бананы являются желтыми", "true"),
        ("Сахар является сладким", "true"),
        ("Соль является сладкой", "fake"),
        ("Молоко является жидким", "true"),
        ("Лед является горячим", "fake"),
        ("Книги сделаны из бумаги", "true"),
        ("Земля вращается вокруг солнца", "true"),
        ("Солнце является планетой", "fake"),
        ("Луна сделана из сыра", "fake"),
        ("Огурец является зеленым", "true"),
    ],
    "pl": [
        ("Ludzie mogą pić wodę", "true"),
        ("Ludzie nie mogą pić wody", "fake"),
        ("Koty są zwierzętami", "true"),
        ("Koty są roślinami", "fake"),
        ("Psy są ssakami", "true"),
        ("Słonie są owadami", "fake"),
        ("Trawa jest zielona", "true"),
        ("Trawa jest fioletowa", "fake"),
        ("Jabłka są owocami", "true"),
        ("Jabłka są niebieskie", "fake"),
        ("Banany są żółte", "true"),
        ("Cukier jest słodki", "true"),
        ("Sól jest słodka", "fake"),
        ("Mleko jest płynne", "true"),
        ("Lód jest gorący", "fake"),
        ("Książki są z papieru", "true"),
        ("Ziemia okrąża słońce", "true"),
        ("Słońce jest planetą", "fake"),
        ("Księżyc jest z sera", "fake"),
        ("Ogórek jest zielony", "true"),
    ],
    "es": [
        ("Los humanos pueden beber agua", "true"),
        ("Los humanos no pueden beber agua", "fake"),
        ("Los gatos son animales", "true"),
        ("Los gatos son plantas", "fake"),
        ("Los perros son mamíferos", "true"),
        ("Los elefantes son insectos", "fake"),
        ("La hierba es verde", "true"),
        ("La hierba es morada", "fake"),
        ("Las manzanas son frutas", "true"),
        ("Las manzanas son azules", "fake"),
        ("Los plátanos son amarillos", "true"),
        ("El azúcar es dulce", "true"),
        ("La sal es dulce", "fake"),
        ("La leche es líquida", "true"),
        ("El hielo es caliente", "fake"),
        ("Los libros son hechos de papel", "true"),
        ("La tierra orbita el sol", "true"),
        ("El sol es un planeta", "fake"),
        ("La luna es hecha de queso", "fake"),
        ("El pepino es verde", "true"),
    ],
    "fr": [
        ("Les humains peuvent boire de l'eau", "true"),
        ("Les humains ne peuvent pas boire de l'eau", "fake"),
        ("Les chats sont des animaux", "true"),
        ("Les chats sont des plantes", "fake"),
        ("Les chiens sont des mammifères", "true"),
        ("Les éléphants sont des insectes", "fake"),
        ("L'herbe est verte", "true"),
        ("L'herbe est violette", "fake"),
        ("Les pommes sont des fruits", "true"),
        ("Les pommes sont bleues", "fake"),
        ("Les bananes sont jaunes", "true"),
        ("Le sucre est sucré", "true"),
        ("Le sel est sucré", "fake"),
        ("Le lait est liquide", "true"),
        ("La glace est chaude", "fake"),
        ("Les livres sont faits de papier", "true"),
        ("La terre orbite autour du soleil", "true"),
        ("Le soleil est une planète", "fake"),
        ("La lune est faite de fromage", "fake"),
        ("Le concombre est vert", "true"),
    ],
    "de": [
        ("Menschen können Wasser trinken", "true"),
        ("Menschen können nicht Wasser trinken", "fake"),
        ("Katzen sind Tiere", "true"),
        ("Katzen sind Pflanzen", "fake"),
        ("Hunde sind Säugetiere", "true"),
        ("Elefanten sind Insekten", "fake"),
        ("Gras ist grün", "true"),
        ("Gras ist lila", "fake"),
        ("Äpfel sind Früchte", "true"),
        ("Äpfel sind blau", "fake"),
        ("Bananen sind gelb", "true"),
        ("Zucker ist süß", "true"),
        ("Salz ist süß", "fake"),
        ("Milch ist flüssig", "true"),
        ("Eis ist heiß", "fake"),
        ("Bücher sind aus Papier", "true"),
        ("Die Erde umkreist die Sonne", "true"),
        ("Die Sonne ist ein Planet", "fake"),
        ("Der Mond ist aus Käse", "fake"),
        ("Die Gurke ist grün", "true"),
    ],
}


def _run_case(index: int, language: str, text: str, expected: str) -> dict:
    start = time.perf_counter()
    translated = normalize_fact_text(text)
    payload = run_factcheck(text=text).to_public_dict()
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    verdict = payload.get("verdict")
    return {
        "index": index,
        "language": language,
        "input": text,
        "translated": translated.translated_text,
        "detected_language": translated.detected_language,
        "expected": expected,
        "actual": verdict,
        "passed": verdict == expected,
        "confidence": payload.get("confidence"),
        "summary": payload.get("summary"),
        "evidence_source_types": [item.get("source_type") for item in payload.get("evidence", [])],
        "fallbacks_used": payload.get("trace", {}).get("fallbacks_used", []),
        "elapsed_ms": elapsed_ms,
    }


def main() -> int:
    rows: list[dict] = []
    index = 0
    for language, cases in LANGUAGE_CASES.items():
        for text, expected in cases:
            index += 1
            rows.append(_run_case(index, language, text, expected))

    passed = sum(1 for row in rows if row["passed"])
    failed = len(rows) - passed
    summary = {
        "total": len(rows),
        "passed": passed,
        "failed": failed,
        "accuracy": round(passed / len(rows), 4) if rows else 0.0,
        "languages": sorted(LANGUAGE_CASES),
    }

    reports_dir = ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    json_path = reports_dir / "multilingual_fact_eval_latest.json"
    md_path = reports_dir / "multilingual_fact_eval_latest.md"
    json_path.write_text(
        json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Multilingual Fact Evaluation",
        "",
        f"- Total: {summary['total']}",
        f"- Passed: {summary['passed']}",
        f"- Failed: {summary['failed']}",
        f"- Accuracy: {summary['accuracy']:.2%}",
        f"- Languages: {', '.join(summary['languages'])}",
        "",
        "| # | Lang | Input | Translation | Expected | Actual | Result |",
        "|---:|---|---|---|---|---|---|",
    ]
    for row in rows:
        result = "PASS" if row["passed"] else "FAIL"
        lines.append(
            "| {index} | {language} | {input} | {translated} | {expected} | {actual} | {result} |".format(
                **row,
                result=result,
            )
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failed:
        print(f"Report: {json_path}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
