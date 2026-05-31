import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import requests

LIAR_RAW_URLS = {
    "train": "https://raw.githubusercontent.com/tfs4/liar_dataset/master/train.tsv",
    "valid": "https://raw.githubusercontent.com/tfs4/liar_dataset/master/valid.tsv",
    "test": "https://raw.githubusercontent.com/tfs4/liar_dataset/master/test.tsv",
}

DATASET_SOURCE = {
    "dataset_name": "LIAR",
    "paper_title": '"Liar, Liar Pants on Fire": A New Benchmark Dataset for Fake News Detection',
    "paper_url": "https://arxiv.org/abs/1705.00648",
    "github_url": "https://github.com/tfs4/liar_dataset",
    "official_zip_url": "https://www.cs.ucsb.edu/~william/data/liar_dataset.zip",
    "origin": "12.8K human-labeled short statements from PolitiFact",
}

LABEL_MAP = {
    "true": "true",
    "mostly-true": "true",
    "false": "fake",
    "pants-fire": "fake",
    "half-true": "uncertain",
    "barely-true": "uncertain",
}


def download_if_needed(cache_dir: Path) -> dict[str, Path]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for split, url in LIAR_RAW_URLS.items():
        path = cache_dir / f"{split}.tsv"
        if not path.exists():
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            path.write_text(response.text, encoding="utf-8")
        out[split] = path
    return out


def load_rows(tsv_path: Path, split: str) -> list[dict]:
    rows = []
    with tsv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for index, cols in enumerate(reader):
            if len(cols) < 14:
                continue
            original_label = cols[1].strip()
            mapped = LABEL_MAP.get(original_label)
            if not mapped:
                continue
            statement_id = cols[0].strip() or f"{split}_{index}"
            statement = cols[2].strip()
            if not statement:
                continue
            rows.append(
                {
                    "id": f"liar_{split}_{statement_id}",
                    "claim_family_id": f"liar_{statement_id}",
                    "text": statement,
                    "expected": mapped,
                    "original_label": original_label,
                    "split": split,
                    "speaker": cols[4].strip(),
                    "subjects": cols[3].strip(),
                    "context": cols[13].strip(),
                    "domain": "politifact.com",
                    "source_type": "factcheck_org",
                    "language": "en",
                    "published_at": "",
                    "url": "https://www.politifact.com/",
                    "dataset_source": DATASET_SOURCE["github_url"],
                }
            )
    return rows


def build_metadata(rows: list[dict]) -> dict:
    by_split = defaultdict(lambda: Counter())
    by_expected = Counter()
    by_original = Counter()
    for row in rows:
        by_split[row["split"]][row["expected"]] += 1
        by_expected[row["expected"]] += 1
        by_original[row["original_label"]] += 1
    return {
        **DATASET_SOURCE,
        "label_mapping": dict(LABEL_MAP),
        "n": len(rows),
        "by_split": {key: dict(value) for key, value in sorted(by_split.items())},
        "by_expected": dict(by_expected),
        "by_original_label": dict(by_original),
    }


def main(cache_dir: str, out_path: str, meta_path: str | None = None) -> None:
    cache_paths = download_if_needed(Path(cache_dir))
    rows = []
    for split in ("train", "valid", "test"):
        rows.extend(load_rows(cache_paths[split], split))

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    metadata = build_metadata(rows)
    metadata["cache_files"] = {key: str(path) for key, path in cache_paths.items()}
    metadata_file = Path(meta_path) if meta_path else out_file.with_suffix(".meta.json")
    metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "dataset": str(out_file),
                "meta": str(metadata_file),
                "n": len(rows),
                "source": DATASET_SOURCE["github_url"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build external LIAR benchmark with explicit provenance")
    parser.add_argument("--cache-dir", default="data/external/liar_official_raw")
    parser.add_argument("--out", default="data/factcheck/external/liar_official_v1_all.jsonl")
    parser.add_argument("--meta-out", default="")
    args = parser.parse_args()
    main(args.cache_dir, args.out, meta_path=args.meta_out or None)
