import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from factcheck.config import build_config
from factcheck.service import run_factcheck


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def safe_div(a: int, b: int) -> float:
    return (a / b) if b else 0.0


def group_metrics(details: list[dict], field_name: str) -> dict[str, dict]:
    grouped = defaultdict(lambda: {"n": 0, "correct": 0, "uncertain": 0, "errors": 0})
    for item in details:
        key = item.get(field_name) or "unknown"
        stats = grouped[key]
        stats["n"] += 1
        if item.get("pred") == item.get("expected"):
            stats["correct"] += 1
        if item.get("pred") == "uncertain":
            stats["uncertain"] += 1
        if item.get("pred") in {"error", "timeout"}:
            stats["errors"] += 1
    return {
        key: {
            **stats,
            "accuracy": round(safe_div(stats["correct"], stats["n"]), 4),
            "uncertain_rate": round(safe_div(stats["uncertain"], stats["n"]), 4),
            "error_rate": round(safe_div(stats["errors"], stats["n"]), 4),
        }
        for key, stats in sorted(grouped.items())
    }


def run_single_row(row: dict, fast: bool) -> dict:
    try:
        result = run_factcheck(text=row.get("text", ""), fast_mode=fast).to_public_dict()
        return {
            "id": row.get("id", ""),
            "expected": row.get("expected", "uncertain"),
            "pred": result.get("verdict", "uncertain"),
            "confidence": result.get("confidence", 0.0),
            "claim": result.get("claim", ""),
            "summary": result.get("summary", ""),
            "evidence_count": len(result.get("evidence", [])),
            "split": row.get("split", ""),
            "original_label": row.get("original_label", ""),
        }
    except Exception as exc:
        return {
            "id": row.get("id", ""),
            "expected": row.get("expected", "uncertain"),
            "pred": "error",
            "confidence": 0.0,
            "error": str(exc),
            "split": row.get("split", ""),
            "original_label": row.get("original_label", ""),
        }


def main(
    dataset_path: str,
    out_path: str,
    fast: bool = True,
    max_rows: int = 0,
    progress_every: int = 500,
    split: str = "",
    workers: int = 1,
) -> None:
    rows = load_jsonl(Path(dataset_path))
    if split:
        rows = [row for row in rows if (row.get("split") or "") == split]
    if max_rows > 0:
        rows = rows[:max_rows]

    details = []
    if int(workers) <= 1:
        for index, row in enumerate(rows, start=1):
            details.append(run_single_row(row, fast=fast))
            if progress_every and index % progress_every == 0:
                print(json.dumps({"processed": index, "total": len(rows), "fast": fast, "workers": workers}, ensure_ascii=False))
    else:
        indexed_results = {}
        with ThreadPoolExecutor(max_workers=int(workers)) as executor:
            future_map = {
                executor.submit(run_single_row, row, fast): index
                for index, row in enumerate(rows, start=1)
            }
            processed = 0
            for future in as_completed(future_map):
                indexed_results[future_map[future]] = future.result()
                processed += 1
                if progress_every and processed % progress_every == 0:
                    print(json.dumps({"processed": processed, "total": len(rows), "fast": fast, "workers": workers}, ensure_ascii=False))
        details = [indexed_results[index] for index in sorted(indexed_results)]

    n = len(details)
    correct = sum(1 for item in details if item.get("pred") == item.get("expected"))
    predictions = Counter(item.get("pred", "other") for item in details)
    payload = {
        "dataset": str(dataset_path),
        "split": split or "all",
        "pipeline_version": build_config(fast_mode=fast).pipeline_version,
        "config": build_config(fast_mode=fast).snapshot().to_dict(),
        "model_versions": dict(build_config(fast_mode=fast).model_versions),
        "n": n,
        "accuracy": safe_div(correct, n),
        "uncertain_rate": safe_div(predictions.get("uncertain", 0), n),
        "error_rate": safe_div(predictions.get("error", 0) + predictions.get("timeout", 0), n),
        "prediction_distribution": dict(predictions),
        "by_split": group_metrics(details, "split"),
        "by_original_label": group_metrics(details, "original_label"),
        "details": details,
    }

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "accuracy": payload["accuracy"],
                "uncertain_rate": payload["uncertain_rate"],
                "error_rate": payload["error_rate"],
                "n": n,
                "out": str(out_file),
                "fast": fast,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a large external evaluation dataset through the fact-check pipeline")
    parser.add_argument("--dataset", default="data/factcheck/external/liar_official_v1_all.jsonl")
    parser.add_argument("--out", default="outputs/factcheck_runs/liar_external_eval.json")
    parser.add_argument("--no-fast", action="store_true")
    parser.add_argument("--max-rows", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=500)
    parser.add_argument("--split", default="")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    main(
        dataset_path=args.dataset,
        out_path=args.out,
        fast=not args.no_fast,
        max_rows=args.max_rows,
        progress_every=args.progress_every,
        split=args.split.strip(),
        workers=max(1, int(args.workers)),
    )
