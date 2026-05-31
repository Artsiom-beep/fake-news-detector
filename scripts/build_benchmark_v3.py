import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from factcheck.source_registry import classify_source


def infer_domain(text: str) -> str:
    low = (text or "").lower()
    mapping = [
        ("reuters", "https://www.reuters.com"),
        ("ap ", "https://apnews.com"),
        ("associated press", "https://apnews.com"),
        ("afp", "https://www.afp.com"),
        ("boomlive", "https://www.boomlive.in"),
        ("newschecker", "https://www.newschecker.in"),
        ("factcheck.org", "https://www.factcheck.org"),
        ("snopes", "https://www.snopes.com"),
        ("politifact", "https://www.politifact.com"),
        ("who ", "https://www.who.int"),
        ("cdc", "https://www.cdc.gov"),
    ]
    for needle, url in mapping:
        if needle in low:
            return url
    return "https://unknown.local"


def infer_published_at(text: str) -> str:
    match = re.search(r"\b(19|20)\d{2}\b", text or "")
    if match:
        return f"{match.group(0)}-01-01"
    return "2026-01-01"


def main(src_path: str, out_path: str):
    rows = [json.loads(line) for line in Path(src_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    out_rows = []
    for row in rows:
        source_url = infer_domain(row.get("text", ""))
        profile = classify_source(source_url)
        out_rows.append(
            {
                "id": row.get("id", ""),
                "claim_family_id": str(row.get("id", "")).replace("_p1", ""),
                "text": row.get("text", ""),
                "expected": row.get("expected", "uncertain"),
                "domain": profile.domain or "unknown",
                "source_type": profile.source_type,
                "language": "en",
                "published_at": infer_published_at(row.get("text", "")),
                "url": source_url if "unknown.local" not in source_url else "",
            }
        )

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in out_rows), encoding="utf-8")
    print({"in": src_path, "out": str(out_file), "n": len(out_rows)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default="data/factcheck/eval_cases_extended_v2.jsonl")
    parser.add_argument("--out", default="data/factcheck/versions/eval_cases_v3_60.jsonl")
    args = parser.parse_args()
    main(args.src, args.out)
