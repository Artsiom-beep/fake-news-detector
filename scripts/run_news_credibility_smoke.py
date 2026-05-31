from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from factcheck.service import run_factcheck


DEFAULT_CASES = [
    {
        "id": "bbc_listing_guardrail",
        "url": "https://www.bbc.com/news",
        "text": "",
        "note": "Listing pages should not be treated as trustworthy article evidence.",
    },
    {
        "id": "synthetic_unknown_text",
        "url": "",
        "text": (
            "A newly discovered city on Mars elected its first mayor today, according to an anonymous viral post. "
            "The article gives no named author, publication date, official source, or independent confirmation. "
        )
        * 5,
        "note": "Unknown text without trusted corroboration should stay low/unknown.",
    },
]


def _run_case(case: dict) -> dict:
    result = run_factcheck(text=case.get("text", ""), url=case.get("url", "")).to_public_dict()
    return {
        "id": case.get("id", ""),
        "url": case.get("url", ""),
        "note": case.get("note", ""),
        "verdict": result.get("verdict"),
        "confidence": result.get("confidence"),
        "claim": result.get("claim"),
        "credibility": result.get("credibility"),
        "evidence_count": len(result.get("evidence", [])),
        "pipeline": result.get("trace", {}).get("mode"),
        "fallbacks": result.get("trace", {}).get("fallbacks_used", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run mixed news credibility smoke checks.")
    parser.add_argument("--url", action="append", default=[], help="Add a news/fact-check URL to the smoke run")
    parser.add_argument("--output", default="reports/news_credibility_smoke.json")
    args = parser.parse_args()

    cases = list(DEFAULT_CASES)
    for index, url in enumerate(args.url, start=1):
        cases.append({"id": f"user_url_{index}", "url": url, "text": "", "note": "User-provided URL"})

    rows = [_run_case(case) for case in cases]
    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
