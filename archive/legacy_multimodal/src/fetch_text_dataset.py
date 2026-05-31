import argparse
from pathlib import Path
import pandas as pd
from datasets import load_dataset


LIAR_TRUE = {'true', 'mostly-true', 'half-true'}
LIAR_FAKE = {'barely-true', 'false', 'pants-fire'}


def map_label(v):
    # LIAR-style strings
    s = str(v).strip().lower()
    if s in LIAR_TRUE:
        return 0
    if s in LIAR_FAKE:
        return 1

    # LIAR2 numeric labels (common ordering: 0..5 = pants-fire..true)
    try:
        iv = int(v)
        return 0 if iv >= 3 else 1
    except Exception:
        return None


def convert_liar(split_ds) -> pd.DataFrame:
    rows = []
    for item in split_ds:
        raw = item.get('label')
        b = map_label(raw)
        if b is None:
            continue
        text = item.get('statement') or item.get('claim') or ''
        rows.append({
            'label': b,
            'text': text,
            'image_path': '',
            'video_path': '',
            'transcript': ''
        })
    return pd.DataFrame(rows)


def main(out_dir: str, dataset_name: str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ds = load_dataset(dataset_name)

    train = convert_liar(ds['train']) if 'train' in ds else pd.DataFrame()
    val = convert_liar(ds['validation']) if 'validation' in ds else pd.DataFrame()
    test = convert_liar(ds['test']) if 'test' in ds else pd.DataFrame()

    train.to_csv(out / 'train.csv', index=False)
    val.to_csv(out / 'val.csv', index=False)
    test.to_csv(out / 'test.csv', index=False)

    print(f'Saved dataset to {out}')
    print(f'train={len(train)}, val={len(val)}, test={len(test)}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--out-dir', default='data/liar')
    p.add_argument('--dataset-name', default='chengxuphd/liar2')
    args = p.parse_args()
    main(args.out_dir, args.dataset_name)
