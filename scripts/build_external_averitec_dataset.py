import argparse
import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import requests

AVERITEC_DEV_URL = "https://huggingface.co/chenxwh/AVeriTeC/resolve/main/data/dev.json"
AVERITEC_DATASET_PAGE = "https://huggingface.co/chenxwh/AVeriTeC"
AVERITEC_PAPER_URL = "https://arxiv.org/abs/2305.13117"

LABEL_MAP = {
    "Supported": "true",
    "Refuted": "fake",
    "Not Enough Evidence": "uncertain",
    "Conflicting Evidence/Cherrypicking": "uncertain",
}


def _extract_archive_inner_url(url: str) -> str:
    text = (url or "").strip()
    if "web.archive.org/web/" not in text:
        return text
    marker_http = text.find("http://", text.find("/web/") + 5)
    marker_https = text.find("https://", text.find("/web/") + 5)
    markers = [marker for marker in (marker_http, marker_https) if marker != -1]
    if not markers:
        return text
    return text[min(markers):]


def _domain_from_url(url: str) -> str:
    try:
        domain = urlparse(_extract_archive_inner_url(url)).netloc.lower().replace("www.", "")
        return domain
    except Exception:
        return ""


def _download_json(url: str, cache_path: Path) -> list[dict]:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    response = requests.get(url, timeout=90, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    cache_path.write_text(response.text, encoding="utf-8")
    return response.json()


def build_rows(items: list[dict]) -> list[dict]:
    rows = []
    for index, item in enumerate(items):
        mapped = LABEL_MAP.get(item.get("label", ""))
        if not mapped:
            continue
        factcheck_url = item.get("fact_checking_article") or ""
        effective_factcheck_url = _extract_archive_inner_url(factcheck_url)
        factcheck_domain = _domain_from_url(factcheck_url) or _domain_from_url(item.get("original_claim_url") or "")
        rows.append(
            {
                "id": f"averitec_dev_{index:04d}",
                "claim_family_id": f"averitec_dev_{index:04d}",
                "text": (item.get("claim") or "").strip(),
                "expected": mapped,
                "original_label": item.get("label", ""),
                "split": "dev",
                "speaker": item.get("speaker"),
                "domain": factcheck_domain or "unknown",
                "source_type": "factcheck_org" if factcheck_domain else "unknown",
                "language": "en",
                "published_at": item.get("claim_date", "") or "",
                "url": effective_factcheck_url,
                "fact_checking_article": factcheck_url,
                "original_claim_url": item.get("original_claim_url") or "",
                "reporting_source": item.get("reporting_source") or "",
                "dataset_source": AVERITEC_DATASET_PAGE,
            }
        )
    return rows


def build_metadata(rows: list[dict], cache_path: Path) -> dict:
    counts = Counter(row["expected"] for row in rows)
    original = Counter(row["original_label"] for row in rows)
    domains = Counter(row["domain"] for row in rows)
    return {
        "dataset_name": "AVeriTeC",
        "split": "dev",
        "dataset_page": AVERITEC_DATASET_PAGE,
        "paper_url": AVERITEC_PAPER_URL,
        "raw_dev_url": AVERITEC_DEV_URL,
        "label_mapping": dict(LABEL_MAP),
        "n": len(rows),
        "by_expected": dict(counts),
        "by_original_label": dict(original),
        "top_domains": dict(domains.most_common(25)),
        "cache_file": str(cache_path),
    }


def main(cache_path: str, out_path: str, meta_path: str | None = None) -> None:
    cache_file = Path(cache_path)
    items = _download_json(AVERITEC_DEV_URL, cache_file)
    rows = build_rows(items)

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    metadata = build_metadata(rows, cache_file)
    meta_file = Path(meta_path) if meta_path else out_file.with_suffix(".meta.json")
    meta_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "dataset": str(out_file),
                "meta": str(meta_file),
                "n": len(rows),
                "source": AVERITEC_DEV_URL,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build external AVeriTeC dev benchmark with explicit provenance")
    parser.add_argument("--cache-path", default="data/external/averitec/dev.json")
    parser.add_argument("--out", default="data/factcheck/external/averitec_dev_v1.jsonl")
    parser.add_argument("--meta-out", default="")
    args = parser.parse_args()
    main(args.cache_path, args.out, meta_path=args.meta_out or None)
