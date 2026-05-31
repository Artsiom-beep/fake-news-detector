import argparse
import json
import multiprocessing as mp
from datetime import datetime
from pathlib import Path
from typing import Dict, List
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "scripts"))

from _factcheck_eval_adapter import run_factcheck_eval_view, set_fast_mode
from eval_report import summarize, render_markdown, LABELS


TEMPLATES = [
    "Quick triage note: {text} How confident should we be?",
    "A colleague phrased it this way: \"{text}\". Does that still hold up?",
    "Claim under review (possible wording noise): {text}.",
    "Before sharing, sanity-check this statement: {text}",
]

HARDENERS = [
    "Some outlets say this is old info; verify anyway.",
    "If this is only partially true, classify conservatively.",
]


def load_jsonl(path: Path) -> List[Dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def base_id(case_id: str) -> str:
    return case_id.replace("_p1", "")


def rewrite_case(row: Dict, variant_idx: int) -> Dict:
    template = TEMPLATES[variant_idx % len(TEMPLATES)]
    hardener = HARDENERS[variant_idx % len(HARDENERS)]
    rewritten = f"{template.format(text=row['text'])} {hardener}".strip()
    return {
        "id": f"{row['id']}_hc{variant_idx + 1}",
        "source_id": row["id"],
        "expected": row["expected"],
        "text": rewritten,
        "template_index": variant_idx % len(TEMPLATES),
        "hardener_index": variant_idx % len(HARDENERS),
    }


def generate_hardcases(source_rows: List[Dict], variants_per_item: int) -> List[Dict]:
    out = []
    for row in source_rows:
        for i in range(variants_per_item):
            out.append(rewrite_case(row, i))
    return out


def _worker(row: Dict, q: mp.Queue, fast_mode: bool = True):
    try:
        set_fast_mode(bool(fast_mode))
        result = run_factcheck_eval_view(row["text"])
        q.put(
            {
                "id": row["id"],
                "source_id": row.get("source_id", ""),
                "expected": row["expected"],
                "pred": result.get("article_verdict", "uncertain"),
                "confidence": result.get("confidence", 0),
            }
        )
    except Exception as e:
        q.put(
            {
                "id": row.get("id", "unknown"),
                "source_id": row.get("source_id", ""),
                "expected": row.get("expected", "uncertain"),
                "pred": "error",
                "confidence": 0,
                "error": str(e),
            }
        )


def eval_rows(rows: List[Dict], timeout: int, fast: bool) -> Dict:
    details = []
    for row in rows:
        q = mp.Queue()
        p = mp.Process(target=_worker, args=(row, q, fast), daemon=True)
        p.start()
        p.join(max(5, int(timeout)))

        if p.is_alive():
            p.terminate()
            p.join(2)
            res = {
                "id": row["id"],
                "source_id": row.get("source_id", ""),
                "expected": row["expected"],
                "pred": "timeout",
                "confidence": 0,
            }
        elif q.empty():
            res = {
                "id": row["id"],
                "source_id": row.get("source_id", ""),
                "expected": row["expected"],
                "pred": "error",
                "confidence": 0,
                "error": "no result",
            }
        else:
            res = q.get()
        details.append(res)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summarize(details, LABELS),
        "details": details,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate + evaluate hard-case rewrites for fact-check set")
    parser.add_argument("--source", default="data/factcheck/splits/test.jsonl")
    parser.add_argument("--guard", nargs="*", default=["data/factcheck/splits/dev.jsonl", "data/factcheck/splits/paraphrase_test.jsonl"])
    parser.add_argument("--variants-per-item", type=int, default=2)
    parser.add_argument("--max-items", type=int, default=0)
    parser.add_argument("--dataset-out", default="data/factcheck/tmp_hardcases_eval.jsonl")
    parser.add_argument("--run-name", default="")
    parser.add_argument("--out-dir", default="outputs/factcheck_runs")
    parser.add_argument("--timeout", type=int, default=40)
    parser.add_argument("--no-fast", action="store_true")
    parser.add_argument("--generate-only", action="store_true")
    args = parser.parse_args()

    source_rows = load_jsonl(Path(args.source))
    blocked_base_ids = set()
    for guard in args.guard:
        guard_path = Path(guard)
        if guard_path.exists():
            blocked_base_ids.update(base_id(str(r["id"])) for r in load_jsonl(guard_path))

    filtered = [r for r in source_rows if base_id(str(r["id"])) not in blocked_base_ids]
    if args.max_items and args.max_items > 0:
        filtered = filtered[: args.max_items]

    hardcases = generate_hardcases(filtered, variants_per_item=max(1, args.variants_per_item))

    dataset_out = Path(args.dataset_out)
    dataset_out.parent.mkdir(parents=True, exist_ok=True)
    dataset_out.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in hardcases), encoding="utf-8")

    run_name = args.run_name.strip() or datetime.now().strftime("hardcases_%Y%m%d_%H%M%S")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.generate_only:
        print(json.dumps({"dataset": str(dataset_out), "n": len(hardcases), "run": run_name}, ensure_ascii=False))
        return

    eval_payload = eval_rows(hardcases, timeout=args.timeout, fast=not args.no_fast)
    report = {
        "run_id": run_name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "hardcase rewrite evaluation",
        "dataset": str(dataset_out),
        "variants_per_item": args.variants_per_item,
        "source_rows": len(filtered),
        "blocked_base_ids": len(blocked_base_ids),
        "overall": eval_payload["summary"],
        "splits": {"hardcases": {"source_file": str(dataset_out), "summary": eval_payload["summary"], "details": eval_payload["details"]}},
    }

    report_json = out_dir / f"{run_name}.json"
    report_md = out_dir / f"{run_name}.md"
    raw_json = out_dir / f"{run_name}_raw_eval.json"

    raw_json.write_text(json.dumps(eval_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md.write_text(render_markdown(report), encoding="utf-8")

    print(
        json.dumps(
            {
                "run_id": run_name,
                "dataset": str(dataset_out),
                "raw_eval": str(raw_json),
                "report_json": str(report_json),
                "report_md": str(report_md),
                "n": len(hardcases),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
