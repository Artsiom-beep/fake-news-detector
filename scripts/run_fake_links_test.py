from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from factcheck.service import run_factcheck


URLS = [
    "https://www.reuters.com/fact-check/ukraine-depot-blast-video-falsely-implied-show-iran-striking-israeli-nuclear-2026-03-05/",
    "https://factcheck.afp.com/doc.afp.com.99HR8G4",
    "https://newschecker.in/fact-check/video-claiming-to-show-iran-striking-israeli-nuclear-site-is-from-2017-blaze-at-ukrainian-arms-depot",
    "https://www.boomlive.in/fact-check/fake-news-viral-video-iran-airstrikes-israel-nuclear-reactor-old-video-ukraine-factcheck-30790",
]


def main() -> int:
    rows = []
    failures = []
    for index, url in enumerate(URLS, 1):
        payload = run_factcheck(url=url).to_public_dict()
        row = {
            "index": index,
            "url": url,
            "verdict": payload.get("verdict"),
            "confidence": payload.get("confidence"),
            "claim": payload.get("claim"),
            "summary": payload.get("summary"),
            "evidence_count": len(payload.get("evidence") or []),
            "fallbacks": (payload.get("trace") or {}).get("fallbacks_used", []),
        }
        rows.append(row)
        if payload.get("verdict") not in {"fake", "uncertain"}:
            failures.append({"url": url, "reason": f"unexpected verdict {payload.get('verdict')}"})
        if payload.get("verdict") == "fake" and not payload.get("evidence"):
            failures.append({"url": url, "reason": "fake verdict without evidence"})

    print(json.dumps(rows, ensure_ascii=False, indent=2))
    if failures:
        print(json.dumps({"failures": failures}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
