import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List

LABELS = ["true", "fake", "uncertain"]


def confusion_from_details(details: List[Dict], labels: List[str]) -> Dict[str, Dict[str, int]]:
    matrix = {e: {p: 0 for p in labels + ["error", "timeout", "other"]} for e in labels}
    for d in details:
        e = d.get("expected", "other")
        p = d.get("pred", "other")
        if e not in matrix:
            continue
        if p not in matrix[e]:
            p = "other"
        matrix[e][p] += 1
    return matrix


def per_class_metrics(details: List[Dict], labels: List[str]) -> Dict[str, Dict]:
    out = {}
    for lbl in labels:
        subset = [d for d in details if d.get("expected") == lbl]
        n = len(subset)
        correct = sum(1 for d in subset if d.get("pred") == lbl)
        out[lbl] = {"n": n, "correct": correct, "accuracy": (correct / n) if n else 0.0}
    return out


def summarize(details: List[Dict], labels: List[str]) -> Dict:
    n = len(details)
    correct = sum(1 for d in details if d.get("pred") == d.get("expected"))
    return {
        "n": n,
        "correct": correct,
        "accuracy": (correct / n) if n else 0.0,
        "per_class": per_class_metrics(details, labels),
        "confusion_matrix": confusion_from_details(details, labels),
        "pred_distribution": dict(Counter(d.get("pred", "other") for d in details)),
    }


def format_confusion_markdown(matrix: Dict[str, Dict[str, int]]) -> str:
    pred_cols = ["true", "fake", "uncertain", "error", "timeout", "other"]
    lines = ["| expected \\ predicted | " + " | ".join(pred_cols) + " |", "|---|---:|---:|---:|---:|---:|---:|"]
    for expected in LABELS:
        vals = [str(matrix[expected][c]) for c in pred_cols]
        lines.append(f"| {expected} | " + " | ".join(vals) + " |")
    return "\n".join(lines)


def render_markdown(report: Dict) -> str:
    lines = [
        "# Factcheck Baseline Evaluation Report",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Source: `{report['source']}`",
        "",
        "## Overall",
        "",
        f"- Total samples: **{report['overall']['n']}**",
        f"- Correct: **{report['overall']['correct']}**",
        f"- Accuracy: **{report['overall']['accuracy']:.4f}**",
        "",
    ]
    for split_name, split in report["splits"].items():
        s = split["summary"]
        lines += [
            f"## {split_name}",
            "",
            f"- N: **{s['n']}**",
            f"- Correct: **{s['correct']}**",
            f"- Accuracy: **{s['accuracy']:.4f}**",
            "",
            "| class | n | correct | accuracy |",
            "|---|---:|---:|---:|",
        ]
        for lbl in LABELS:
            pc = s["per_class"][lbl]
            lines.append(f"| {lbl} | {pc['n']} | {pc['correct']} | {pc['accuracy']:.4f} |")
        lines += ["", "Confusion matrix:", "", format_confusion_markdown(s["confusion_matrix"]), ""]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Build consolidated eval report from split result files")
    p.add_argument("--dev", default="outputs/factcheck_runs/v3_baseline_dev.json")
    p.add_argument("--test", default="outputs/factcheck_runs/v3_baseline_test.json")
    p.add_argument("--paraphrase", default="outputs/factcheck_runs/v3_baseline_paraphrase.json")
    p.add_argument("--out-dir", default="outputs/factcheck_runs")
    p.add_argument("--run-name", default="")
    args = p.parse_args()

    split_inputs = {"dev": args.dev, "test": args.test, "paraphrase": args.paraphrase}
    split_reports = {}
    all_details = []

    for name, path_str in split_inputs.items():
        path = Path(path_str)
        payload = json.loads(path.read_text(encoding="utf-8"))
        details = payload.get("details", [])
        split_reports[name] = {"source_file": str(path), "summary": summarize(details, LABELS), "details": details}
        all_details.extend(details)

    run_id = args.run_name.strip() or datetime.now().strftime("baseline_report_%Y%m%d_%H%M%S")
    report = {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "precomputed split baseline files",
        "splits": split_reports,
        "overall": summarize(all_details, LABELS),
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{run_id}.json"
    md_path = out_dir / f"{run_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")

    print(json.dumps({"run_id": run_id, "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
