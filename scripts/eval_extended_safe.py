import json
import multiprocessing as mp
from pathlib import Path

from _factcheck_eval_adapter import run_factcheck_eval_view, set_fast_mode


def worker(row, q, fast_mode: bool = True):
    try:
        set_fast_mode(bool(fast_mode))
        out = run_factcheck_eval_view(row['text'])
        q.put({
            'id': row['id'],
            'expected': row['expected'],
            'pred': out.get('article_verdict'),
            'confidence': out.get('confidence', 0),
        })
    except Exception as e:
        q.put({
            'id': row['id'],
            'expected': row['expected'],
            'pred': 'error',
            'confidence': 0,
            'error': str(e),
        })


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', default='data/factcheck/eval_cases_extended.jsonl')
    p.add_argument('--out', default='outputs/factcheck_runs/eval_results_extended_safe_fast.json')
    p.add_argument('--timeout', type=int, default=35)
    p.add_argument('--fast', action='store_true', default=True)
    args = p.parse_args()

    data_path = Path(args.dataset)
    out_path = Path(args.out)

    rows = [json.loads(x) for x in data_path.read_text(encoding='utf-8').splitlines() if x.strip()]

    details = []
    for row in rows:
        q = mp.Queue()
        p = mp.Process(target=worker, args=(row, q, args.fast), daemon=True)
        p.start()
        p.join(max(5, int(args.timeout)))

        if p.is_alive():
            p.terminate()
            p.join(3)
            details.append({
                'id': row['id'],
                'expected': row['expected'],
                'pred': 'timeout',
                'confidence': 0,
            })
            continue

        if q.empty():
            details.append({
                'id': row['id'],
                'expected': row['expected'],
                'pred': 'error',
                'confidence': 0,
                'error': 'no result',
            })
        else:
            details.append(q.get())

    correct = sum(1 for d in details if d['pred'] == d['expected'])
    acc = correct / max(len(details), 1)

    labels = ['true', 'fake', 'uncertain']
    per_class = {}
    for lbl in labels:
        subset = [d for d in details if d['expected'] == lbl]
        ok = sum(1 for d in subset if d['pred'] == lbl)
        per_class[lbl] = {
            'n': len(subset),
            'correct': ok,
            'accuracy': (ok / len(subset)) if subset else 0.0,
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out = {'accuracy': acc, 'per_class': per_class, 'details': details}
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'accuracy': acc, 'n': len(details), 'per_class': per_class, 'out': str(out_path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
