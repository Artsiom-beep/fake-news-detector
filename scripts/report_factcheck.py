import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def main(eval_path: str, out_md_path: str):
    payload = json.loads(Path(eval_path).read_text(encoding="utf-8"))
    details = payload.get("details", [])
    by_class = defaultdict(lambda: {"n": 0, "ok": 0})
    preds = Counter(item.get("pred", "uncertain") for item in details)

    for item in details:
        expected = item.get("expected", "uncertain")
        by_class[expected]["n"] += 1
        if item.get("pred") == expected:
            by_class[expected]["ok"] += 1

    lines = [
        "# Fact-check Evaluation Report",
        f"Pipeline: {payload.get('pipeline_version', 'unknown')}",
        f"Overall accuracy: {payload.get('accuracy', 0):.3f}",
        f"Uncertain rate: {payload.get('uncertain_rate', 0):.3f}",
        f"Error rate: {payload.get('error_rate', 0):.3f}",
        "",
        "Prediction distribution:",
    ]
    for label, count in sorted(preds.items()):
        lines.append(f"- {label}: {count}")
    lines.extend(["", "Per-class accuracy:"])
    for label in ["true", "fake", "uncertain"]:
        total = by_class[label]["n"]
        ok = by_class[label]["ok"]
        acc = ok / total if total else 0.0
        lines.append(f"- {label}: {acc:.3f} ({ok}/{total})")

    out_path = Path(out_md_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", default="outputs/factcheck_runs/eval_results_v1.json")
    parser.add_argument("--out-md", default="outputs/factcheck_runs/final_report.md")
    args = parser.parse_args()
    main(args.eval, args.out_md)
