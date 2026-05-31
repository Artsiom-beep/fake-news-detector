import json
import argparse
from pathlib import Path

from _factcheck_eval_adapter import run_factcheck_eval_view, set_fast_mode

LABELS = ['true', 'fake', 'uncertain']


def eval_split(path: Path):
    rows = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
    cm = {t: {p: 0 for p in LABELS} for t in LABELS}
    details = []
    for r in rows:
        out = run_factcheck_eval_view(r['text'])
        pred = out.get('article_verdict', 'uncertain')
        if pred not in LABELS:
            pred = 'uncertain'
        exp = r['expected'] if r['expected'] in LABELS else 'uncertain'
        cm[exp][pred] += 1
        details.append({'id': r['id'], 'expected': exp, 'pred': pred, 'confidence': out.get('confidence', 0)})

    n = len(rows)
    correct = sum(cm[l][l] for l in LABELS)
    fake_total = sum(cm['fake'].values())
    fake_recall = cm['fake']['fake'] / fake_total if fake_total else 0.0
    fake_overpred = sum(cm[t]['fake'] for t in LABELS if t != 'fake')
    return {
        'n': n,
        'accuracy': correct / max(n, 1),
        'fake_recall': fake_recall,
        'fake_overpred': fake_overpred,
        'confusion': cm,
        'details': details,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--splits-dir', default='data/factcheck/splits')
    p.add_argument('--splits', nargs='+', default=['dev', 'test', 'paraphrase_test'])
    p.add_argument('--out', default='outputs/factcheck_runs/decision_calibration_eval.json')
    p.add_argument('--fast-nli', action='store_true')
    args = p.parse_args()

    if args.fast_nli:
        set_fast_mode(True)

    out = {}
    for split in args.splits:
        out[split] = eval_split(Path(args.splits_dir) / f'{split}.jsonl')

    macro_acc = sum(v['accuracy'] for v in out.values()) / max(len(out), 1)
    out['_summary'] = {'macro_accuracy': macro_acc}

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out': str(out_path), 'summary': out['_summary']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
