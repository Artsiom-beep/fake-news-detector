import argparse
import json
import multiprocessing as mp
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from factcheck.config import build_config
from factcheck.service import run_factcheck


def _worker(row, queue, fast_mode: bool):
    try:
        result = run_factcheck(text=row.get("text", ""), fast_mode=fast_mode).to_public_dict()
        queue.put(
            {
                "id": row.get("id", ""),
                "expected": row.get("expected", "uncertain"),
                "pred": result.get("verdict", "uncertain"),
                "confidence": result.get("confidence", 0.0),
                "claim": result.get("claim", ""),
                "summary": result.get("summary", ""),
                "evidence_count": len(result.get("evidence", [])),
            }
        )
    except Exception as exc:
        queue.put(
            {
                "id": row.get("id", ""),
                "expected": row.get("expected", "uncertain"),
                "pred": "error",
                "confidence": 0.0,
                "error": str(exc),
            }
        )


def main(dataset_path: str, out_path: str, timeout: int = 40, fast: bool = True):
    rows = [json.loads(line) for line in Path(dataset_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    details = []

    for row in rows:
        queue = mp.Queue()
        process = mp.Process(target=_worker, args=(row, queue, fast), daemon=True)
        process.start()
        process.join(max(5, int(timeout)))

        if process.is_alive():
            process.terminate()
            process.join(2)
            item = {
                "id": row.get("id", ""),
                "expected": row.get("expected", "uncertain"),
                "pred": "timeout",
                "confidence": 0.0,
            }
        elif queue.empty():
            item = {
                "id": row.get("id", ""),
                "expected": row.get("expected", "uncertain"),
                "pred": "error",
                "confidence": 0.0,
                "error": "no result",
            }
        else:
            item = queue.get()
        details.append(item)

    n = len(details)
    predictions = Counter(item.get("pred", "other") for item in details)
    accuracy = sum(1 for item in details if item.get("pred") == item.get("expected")) / max(n, 1)
    config = build_config(fast_mode=fast)
    payload = {
        "dataset": str(dataset_path),
        "pipeline_version": config.pipeline_version,
        "config": config.snapshot().to_dict(),
        "model_versions": dict(config.model_versions),
        "n": n,
        "accuracy": accuracy,
        "uncertain_rate": predictions.get("uncertain", 0) / max(n, 1),
        "error_rate": (predictions.get("error", 0) + predictions.get("timeout", 0)) / max(n, 1),
        "details": details,
    }

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "accuracy": accuracy,
                "n": n,
                "out": str(out_file),
                "timeout": timeout,
                "fast": fast,
                "dataset": str(dataset_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/factcheck/versions/eval_cases_v3_60.jsonl")
    parser.add_argument("--out", default="outputs/factcheck_runs/eval_results_v1.json")
    parser.add_argument("--timeout", type=int, default=40)
    parser.add_argument("--no-fast", action="store_true")
    args = parser.parse_args()
    main(args.dataset, args.out, timeout=args.timeout, fast=not args.no_fast)
