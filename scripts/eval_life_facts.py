from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from factcheck.config import build_config
from factcheck.service import run_factcheck


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _evaluate_row(row: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        result = run_factcheck(text=row.get("text", "")).to_public_dict()
        elapsed_ms = (time.perf_counter() - start) * 1000
        evidence = result.get("evidence", [])
        return {
            "id": row.get("id", ""),
            "claim_family_id": row.get("claim_family_id", ""),
            "text": row.get("text", ""),
            "expected": row.get("expected", "uncertain"),
            "pred": result.get("verdict", "uncertain"),
            "confidence": result.get("confidence", 0.0),
            "category": row.get("category", "unknown"),
            "source_type": row.get("source_type", "unknown"),
            "summary": result.get("summary", ""),
            "evidence_count": len(evidence),
            "top_evidence_url": evidence[0].get("url", "") if evidence else "",
            "fallbacks_used": result.get("trace", {}).get("fallbacks_used", []),
            "decision_reasons": result.get("trace", {}).get("decision_reasons", []),
            "elapsed_ms": round(elapsed_ms, 2),
            "ok": result.get("verdict", "uncertain") == row.get("expected", "uncertain"),
        }
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {
            "id": row.get("id", ""),
            "claim_family_id": row.get("claim_family_id", ""),
            "text": row.get("text", ""),
            "expected": row.get("expected", "uncertain"),
            "pred": "error",
            "confidence": 0.0,
            "category": row.get("category", "unknown"),
            "source_type": row.get("source_type", "unknown"),
            "summary": "",
            "evidence_count": 0,
            "top_evidence_url": "",
            "fallbacks_used": [],
            "decision_reasons": [],
            "elapsed_ms": round(elapsed_ms, 2),
            "ok": False,
            "error": str(exc),
        }


def _breakdown(details: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in details:
        grouped[item.get(key, "unknown")].append(item)

    payload: dict[str, dict[str, Any]] = {}
    for name, items in sorted(grouped.items()):
        n = len(items)
        predictions = Counter(item.get("pred", "unknown") for item in items)
        payload[name] = {
            "n": n,
            "accuracy": sum(1 for item in items if item.get("ok")) / max(n, 1),
            "uncertain_rate": predictions.get("uncertain", 0) / max(n, 1),
            "predictions": dict(sorted(predictions.items())),
        }
    return payload


def _build_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Life Facts v1 Report",
        "",
        f"- Dataset: `{payload['dataset']}`",
        f"- Pipeline: `{payload['pipeline_version']}`",
        f"- Cases: `{payload['n']}`",
        f"- Accuracy: `{_pct(payload['accuracy'])}`",
        f"- Hard verdict precision: `{_pct(payload['hard_verdict_precision'])}`",
        f"- Hard verdict coverage: `{_pct(payload['hard_verdict_coverage'])}`",
        f"- Uncertain rate: `{_pct(payload['uncertain_rate'])}`",
        f"- Error rate: `{_pct(payload['error_rate'])}`",
        "",
        "## Breakdown By Category",
        "",
        "| Category | N | Accuracy | Uncertain | Predictions |",
        "|---|---:|---:|---:|---|",
    ]
    for category, item in payload["by_category"].items():
        lines.append(
            f"| {category} | {item['n']} | {_pct(item['accuracy'])} | "
            f"{_pct(item['uncertain_rate'])} | `{json.dumps(item['predictions'], sort_keys=True)}` |"
        )

    lines.extend(
        [
            "",
            "## Breakdown By Source Type",
            "",
            "| Source Type | N | Accuracy | Uncertain | Predictions |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for source_type, item in payload["by_source_type"].items():
        lines.append(
            f"| {source_type} | {item['n']} | {_pct(item['accuracy'])} | "
            f"{_pct(item['uncertain_rate'])} | `{json.dumps(item['predictions'], sort_keys=True)}` |"
        )

    failures = [item for item in payload["details"] if not item.get("ok")]
    lines.extend(["", "## Failures", ""])
    if not failures:
        lines.append("No failures.")
    else:
        lines.append("| ID | Expected | Pred | Confidence | Category | Text | Summary |")
        lines.append("|---|---|---|---:|---|---|---|")
        for item in failures[:50]:
            text = str(item.get("text", "")).replace("|", "\\|")
            summary = str(item.get("summary", "")).replace("|", "\\|")
            lines.append(
                f"| {item.get('id', '')} | {item.get('expected', '')} | {item.get('pred', '')} | "
                f"{float(item.get('confidence', 0.0)):.3f} | {item.get('category', '')} | {text} | {summary} |"
            )

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the best-accuracy pipeline on life_facts_v1.")
    parser.add_argument("--dataset", default="data/factcheck/versions/life_facts_v1.jsonl")
    parser.add_argument("--json-out", default="outputs/factcheck_runs/life_facts_v1_results.json")
    parser.add_argument("--md-out", default="reports/life_facts_v1_report.md")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    dataset_path = ROOT / args.dataset
    rows = _load_jsonl(dataset_path)
    if args.limit > 0:
        rows = rows[: args.limit]

    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    details = [_evaluate_row(row) for row in rows]
    n = len(details)
    predictions = Counter(item.get("pred", "unknown") for item in details)
    hard_predictions = [item for item in details if item.get("pred") in {"true", "fake"}]
    config = build_config()
    payload = {
        "dataset": str(dataset_path),
        "dataset_version": "life_facts_v1",
        "pipeline_version": config.pipeline_version,
        "config": config.snapshot().to_dict(),
        "model_versions": dict(config.model_versions),
        "started_at": started_at,
        "n": n,
        "accuracy": sum(1 for item in details if item.get("ok")) / max(n, 1),
        "hard_verdict_precision": (
            sum(1 for item in hard_predictions if item.get("ok")) / max(len(hard_predictions), 1)
        ),
        "hard_verdict_coverage": len(hard_predictions) / max(n, 1),
        "uncertain_rate": predictions.get("uncertain", 0) / max(n, 1),
        "error_rate": predictions.get("error", 0) / max(n, 1),
        "predictions": dict(sorted(predictions.items())),
        "by_category": _breakdown(details, "category"),
        "by_source_type": _breakdown(details, "source_type"),
        "details": details,
    }

    json_out = ROOT / args.json_out
    md_out = ROOT / args.md_out
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_out.write_text(_build_report(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "dataset_version": payload["dataset_version"],
                "n": payload["n"],
                "accuracy": round(payload["accuracy"], 4),
                "hard_verdict_precision": round(payload["hard_verdict_precision"], 4),
                "hard_verdict_coverage": round(payload["hard_verdict_coverage"], 4),
                "uncertain_rate": round(payload["uncertain_rate"], 4),
                "error_rate": round(payload["error_rate"], 4),
                "json_out": str(json_out),
                "md_out": str(md_out),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
