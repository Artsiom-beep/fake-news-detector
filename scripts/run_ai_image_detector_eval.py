from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from factcheck.image_analysis import run_ai_image_check


DEFAULT_MANIFEST = ROOT / "data" / "image_eval" / "v1" / "manifest.jsonl"
DEFAULT_HISTORY_DIR = ROOT / "reports" / "image_detector_runs"
REQUIRED_MANIFEST_FIELDS = {"id", "expected", "source", "license_or_origin", "local_path", "notes"}


def _download(url: str, output_path: Path, timeout: int = 45) -> tuple[bool, str]:
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            return False, f"not_image:{content_type}"
        output_path.write_bytes(response.content)
        return True, response.url
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}"


def _resolve_repo_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return ROOT / path


def _repo_relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _load_manifest(manifest_path: Path) -> list[dict]:
    cases: list[dict] = []
    for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        missing = sorted(REQUIRED_MANIFEST_FIELDS - set(case))
        if missing:
            raise ValueError(f"{manifest_path}:{line_number} missing fields: {', '.join(missing)}")
        expected = str(case.get("expected", "")).lower()
        if expected not in {"ai", "real"}:
            raise ValueError(f"{manifest_path}:{line_number} expected must be 'ai' or 'real'")
        case["expected"] = expected
        cases.append(case)
    return cases


def _source_url(case: dict) -> str:
    source_url = str(case.get("source_url", "")).strip()
    if source_url:
        return source_url
    source = str(case.get("source", "")).strip()
    if source.startswith(("http://", "https://")):
        return source
    return ""


def _classify_expected(expected: str, label: str) -> str:
    if expected == "ai":
        if label == "likely_ai":
            return "correct"
        if label == "likely_not_ai":
            return "wrong"
        return "abstained"
    if expected == "real":
        if label == "likely_not_ai":
            return "correct"
        if label == "likely_ai":
            return "wrong"
        return "abstained"
    return "unknown"


def _run_case(case: dict, image_path: Path) -> dict:
    payload = run_ai_image_check(image_path.read_bytes(), filename=image_path.name).to_public_dict()
    analysis = payload.get("image_analysis") or {}
    label = analysis.get("ai_label", "uncertain")
    expected = case["expected"]
    return {
        "id": case["id"],
        "expected": expected,
        "outcome": _classify_expected(expected, label),
        "ai_label": label,
        "ai_generated_score": analysis.get("ai_generated_score", 0.0),
        "summary": payload.get("summary", ""),
        "source": case.get("source", ""),
        "source_url": case.get("source_url", ""),
        "license_or_origin": case.get("license_or_origin", ""),
        "local_path": _repo_relative(image_path),
        "notes": case.get("notes", ""),
        "reasons": analysis.get("reasons", []),
        "warnings": analysis.get("warnings", []),
    }


def _metrics(rows: list[dict]) -> dict:
    evaluated = [row for row in rows if row.get("outcome") in {"correct", "wrong", "abstained"}]
    by_expected: dict[str, dict[str, int]] = {}
    for row in evaluated:
        bucket = by_expected.setdefault(row["expected"], {"total": 0, "correct": 0, "wrong": 0, "abstained": 0})
        bucket["total"] += 1
        bucket[row["outcome"]] += 1

    hard = [row for row in evaluated if row["ai_label"] in {"likely_ai", "likely_not_ai"}]
    hard_correct = sum(1 for row in hard if row["outcome"] == "correct")
    false_positive_real_as_ai = sum(1 for row in evaluated if row["expected"] == "real" and row["ai_label"] == "likely_ai")
    false_negative_ai_as_real = sum(1 for row in evaluated if row["expected"] == "ai" and row["ai_label"] == "likely_not_ai")
    real_abstentions = sum(1 for row in evaluated if row["expected"] == "real" and row["ai_label"] == "uncertain")
    ai_abstentions = sum(1 for row in evaluated if row["expected"] == "ai" and row["ai_label"] == "uncertain")
    return {
        "manifest_total": len(rows),
        "total": len(evaluated),
        "not_evaluated": len(rows) - len(evaluated),
        "hard_predictions": len(hard),
        "hard_precision": round(hard_correct / len(hard), 4) if hard else 0.0,
        "coverage": round(len(hard) / len(evaluated), 4) if evaluated else 0.0,
        "false_positive_real_as_ai": false_positive_real_as_ai,
        "false_negative_ai_as_real": false_negative_ai_as_real,
        "real_abstentions": real_abstentions,
        "ai_abstentions": ai_abstentions,
        "by_expected": by_expected,
    }


def _md_cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _write_markdown(rows: list[dict], metrics: dict, output_path: Path, run_meta: dict) -> None:
    lines = [
        "# AI Image Detector Eval",
        "",
        f"Run ID: `{run_meta['run_id']}`",
        f"Dataset: `{run_meta['manifest']}`",
        f"Model: `{run_meta['model']}`",
        "",
        "Sources:",
        "- AI-generated images and real images are listed in the versioned manifest.",
        "- False `likely_ai` labels on real images are tracked separately because they are the highest-risk failure mode.",
        "",
        f"Manifest cases: {metrics['manifest_total']}",
        f"Evaluated cases: {metrics['total']}",
        f"Not evaluated: {metrics['not_evaluated']}",
        f"Hard predictions: {metrics['hard_predictions']}",
        f"Hard precision: {metrics['hard_precision']:.2%}",
        f"Coverage: {metrics['coverage']:.2%}",
        f"False positives, real labeled AI: {metrics['false_positive_real_as_ai']}",
        f"False negatives, AI labeled real: {metrics['false_negative_ai_as_real']}",
        f"Real abstentions: {metrics['real_abstentions']}",
        f"AI abstentions: {metrics['ai_abstentions']}",
        "",
        "| id | expected | label | score | outcome | source | notes |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        source = row.get("source") or row.get("source_url") or row.get("local_path", "")
        lines.append(
            f"| {_md_cell(row['id'])} | {_md_cell(row['expected'])} | {_md_cell(row['ai_label'])} | "
            f"{float(row['ai_generated_score']):.3f} | {_md_cell(row['outcome'])} | {_md_cell(source)} | {_md_cell(row.get('notes', ''))} |"
        )
    lines.extend(["", "## Notes"])
    for row in rows:
        reason_text = ", ".join(str(item) for item in row.get("reasons", [])[:6])
        warning_text = ", ".join(str(item) for item in row.get("warnings", [])[:6])
        lines.append(f"- `{row['id']}`: reasons={reason_text or 'none'}; warnings={warning_text or 'none'}")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the AI-image detector against a versioned image manifest.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST.relative_to(ROOT)))
    parser.add_argument("--out-dir", default="outputs/ai_image_eval")
    parser.add_argument("--history-dir", default=str(DEFAULT_HISTORY_DIR.relative_to(ROOT)))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--limit", type=int, default=0, help="Optional total case limit for quick runs")
    parser.add_argument("--refresh", action="store_true", help="Re-download images even when a local copy exists")
    parser.add_argument("--existing-only", action="store_true", help="Evaluate only images already present on disk")
    parser.add_argument("--width", type=int, default=610, help=argparse.SUPPRESS)
    parser.add_argument("--height", type=int, default=385, help=argparse.SUPPRESS)
    parser.add_argument("--ai-delay", type=float, default=8.0, help=argparse.SUPPRESS)
    args = parser.parse_args()

    os.environ.setdefault("FACTCHECK_AI_IMAGE_MODEL", "haywoodsloan/ai-image-detector-deploy")
    manifest_path = _resolve_repo_path(args.manifest)
    out_dir = ROOT / args.out_dir
    history_dir = _resolve_repo_path(args.history_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    history_dir.mkdir(parents=True, exist_ok=True)

    cases = _load_manifest(manifest_path)
    if args.limit > 0:
        cases = cases[: args.limit]

    rows: list[dict] = []
    for case in cases:
        image_path = _resolve_repo_path(case["local_path"])
        if image_path.exists() and image_path.stat().st_size > 0 and not args.refresh:
            ok, resolved = True, _source_url(case)
        else:
            if args.existing_only:
                rows.append(
                    {
                        "id": case["id"],
                        "expected": case["expected"],
                        "outcome": "missing_local_file",
                        "ai_label": "not_run",
                        "ai_generated_score": 0.0,
                        "source": case.get("source", ""),
                        "source_url": case.get("source_url", ""),
                        "license_or_origin": case.get("license_or_origin", ""),
                        "local_path": _repo_relative(image_path),
                        "notes": case.get("notes", ""),
                        "reasons": [],
                        "warnings": ["missing_local_file"],
                    }
                )
                continue
            source_url = _source_url(case)
            if not source_url:
                ok, resolved = False, "missing_source_url"
            else:
                image_path.parent.mkdir(parents=True, exist_ok=True)
                ok, resolved = _download(source_url, image_path)
        if not ok:
            rows.append(
                {
                    "id": case["id"],
                    "expected": case["expected"],
                    "outcome": "download_failed",
                    "ai_label": "not_run",
                    "ai_generated_score": 0.0,
                    "source": case.get("source", ""),
                    "source_url": case.get("source_url", ""),
                    "license_or_origin": case.get("license_or_origin", ""),
                    "local_path": _repo_relative(image_path),
                    "notes": case.get("notes", ""),
                    "reasons": [],
                    "warnings": [resolved],
                }
            )
            continue
        if resolved:
            case["source_url"] = resolved
        rows.append(_run_case(case, image_path))

    metrics = _metrics(rows)
    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_meta = {
        "run_id": run_id,
        "manifest": _repo_relative(manifest_path),
        "model": os.getenv("FACTCHECK_AI_IMAGE_MODEL", ""),
    }
    payload = {"run": run_meta, "metrics": metrics, "rows": rows}
    json_path = out_dir / "ai_image_detector_eval.json"
    md_path = out_dir / "ai_image_detector_eval.md"
    history_json_path = history_dir / f"{run_id}.json"
    history_md_path = history_dir / f"{run_id}.md"
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)
    json_path.write_text(json_text, encoding="utf-8")
    history_json_path.write_text(json_text, encoding="utf-8")
    _write_markdown(rows, metrics, md_path, run_meta)
    _write_markdown(rows, metrics, history_md_path, run_meta)
    print(
        json.dumps(
            {
                "run": run_meta,
                "metrics": metrics,
                "json": _repo_relative(json_path),
                "markdown": _repo_relative(md_path),
                "history_json": _repo_relative(history_json_path),
                "history_markdown": _repo_relative(history_md_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
