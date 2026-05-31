import argparse
import json
from collections import Counter
from pathlib import Path

try:
    from .factcheck.service import run_factcheck
except ImportError:
    from factcheck.service import run_factcheck


def main(dataset_path: str, out_path: str, fast_mode: bool = True):
    rows = [json.loads(line) for line in Path(dataset_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    details = []
    correct = 0

    for row in rows:
        result = run_factcheck(text=row.get("text", ""), fast_mode=fast_mode).to_public_dict()
        pred = result.get("verdict", "uncertain")
        correct += int(pred == row.get("expected"))
        details.append(
            {
                "id": row.get("id", ""),
                "expected": row.get("expected", "uncertain"),
                "pred": pred,
                "confidence": result.get("confidence", 0.0),
                "claim": result.get("claim", ""),
                "summary": result.get("summary", ""),
                "evidence_count": len(result.get("evidence", [])),
            }
        )

    n = len(rows)
    accuracy = correct / max(n, 1)
    predictions = Counter(item["pred"] for item in details)
    payload = {
        "dataset": dataset_path,
        "pipeline_version": "factcheck_v1",
        "n": n,
        "accuracy": accuracy,
        "uncertain_rate": predictions.get("uncertain", 0) / max(n, 1),
        "error_rate": predictions.get("error", 0) / max(n, 1),
        "details": details,
    }

    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"accuracy": accuracy, "n": n, "out": str(out_file)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="data/factcheck/versions/eval_cases_v3_60.jsonl")
    parser.add_argument("--out", default="outputs/factcheck_runs/eval_results_v1.json")
    parser.add_argument("--no-fast", action="store_true")
    args = parser.parse_args()
    main(args.dataset, args.out, fast_mode=not args.no_fast)
