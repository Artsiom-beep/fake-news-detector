import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List


def load_json(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def safe_div(a: int, b: int) -> float:
    return (a / b) if b else 0.0


def build_index(dataset_rows: List[Dict]) -> Dict[str, Dict]:
    return {str(row.get("id")): row for row in dataset_rows}


def _group_metrics(eval_details: List[Dict], dataset_index: Dict[str, Dict], field_name: str) -> Dict[str, Dict]:
    grouped = defaultdict(lambda: {"n": 0, "correct": 0, "uncertain": 0, "errors": 0})
    for detail in eval_details:
        row = dataset_index.get(str(detail.get("id")), {})
        key = row.get(field_name) or "unknown"
        stats = grouped[key]
        stats["n"] += 1
        if detail.get("pred") == detail.get("expected"):
            stats["correct"] += 1
        if detail.get("pred") == "uncertain":
            stats["uncertain"] += 1
        if detail.get("pred") in {"error", "timeout"}:
            stats["errors"] += 1
    out = {}
    for key, stats in sorted(grouped.items()):
        out[key] = {
            **stats,
            "accuracy": round(safe_div(stats["correct"], stats["n"]), 4),
            "uncertain_rate": round(safe_div(stats["uncertain"], stats["n"]), 4),
            "error_rate": round(safe_div(stats["errors"], stats["n"]), 4),
        }
    return out


def summarize(eval_details: List[Dict], dataset_index: Dict[str, Dict]) -> Dict:
    n = len(eval_details)
    correct = sum(1 for detail in eval_details if detail.get("pred") == detail.get("expected"))
    uncertain = sum(1 for detail in eval_details if detail.get("pred") == "uncertain")
    errors = sum(1 for detail in eval_details if detail.get("pred") in {"error", "timeout"})
    return {
        "n": n,
        "correct": correct,
        "accuracy": round(safe_div(correct, n), 4),
        "uncertain": uncertain,
        "uncertain_rate": round(safe_div(uncertain, n), 4),
        "errors": errors,
        "error_rate": round(safe_div(errors, n), 4),
        "by_domain": _group_metrics(eval_details, dataset_index, "domain"),
        "by_source_type": _group_metrics(eval_details, dataset_index, "source_type"),
    }


def append_jsonl(path: Path, row: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Register eval run metrics into benchmark history")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--eval", required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--pipeline-version", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--history", default="benchmarks/benchmark_runs.jsonl")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    eval_path = Path(args.eval)
    history_path = Path(args.history)

    dataset_rows = load_jsonl(dataset_path)
    eval_payload = load_json(eval_path)
    metrics = summarize(eval_payload.get("details", []), build_index(dataset_rows))
    config_blob = json.dumps(eval_payload.get("config", {}), ensure_ascii=False, sort_keys=True)

    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "dataset_version": args.dataset_version,
        "dataset_path": str(dataset_path),
        "dataset_n": len(dataset_rows),
        "pipeline_version": args.pipeline_version or eval_payload.get("pipeline_version", "unknown"),
        "config_hash": hashlib.sha1(config_blob.encode("utf-8")).hexdigest(),
        "model_versions": eval_payload.get("model_versions", {}),
        "eval_path": str(eval_path),
        "metrics": metrics,
        "notes": args.notes.strip(),
    }

    append_jsonl(history_path, record)
    print(json.dumps({"history": str(history_path), "record": record}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
