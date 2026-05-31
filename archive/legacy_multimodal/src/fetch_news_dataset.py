import argparse
from pathlib import Path

import pandas as pd
from datasets import DatasetDict, load_dataset


REQUIRED_COLUMNS = ['label', 'text', 'image_path', 'video_path', 'transcript']


def _to_binary(label_value):
    """
    Normalize labels to project convention:
      0 = real
      1 = fake

    Supports ints and common strings.
    """
    if isinstance(label_value, (int, float)):
        iv = int(label_value)
        if iv in (0, 1):
            # In our default HF source, 1=real, 0=fake.
            return 0 if iv == 1 else 1
        return None

    s = str(label_value).strip().lower()
    if s in {'real', 'true', 'reliable'}:
        return 0
    if s in {'fake', 'false', 'unreliable'}:
        return 1
    return None


def _convert_split(ds, title_col: str, text_col: str, label_col: str):
    rows = []
    for item in ds:
        y = _to_binary(item.get(label_col))
        if y is None:
            continue

        title = str(item.get(title_col, '') or '').strip() if title_col else ''
        text = str(item.get(text_col, '') or '').strip() if text_col else ''
        merged = f"{title}\n\n{text}".strip() if title else text
        if not merged:
            continue

        rows.append({
            'label': y,
            'text': merged,
            'image_path': '',
            'video_path': '',
            'transcript': '',
        })

    df = pd.DataFrame(rows, columns=REQUIRED_COLUMNS)
    return df


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset-name', default='ErfanMoosaviMonazzah/fake-news-detection-dataset-English')
    p.add_argument('--train-split', default='train')
    p.add_argument('--val-split', default='validation')
    p.add_argument('--test-split', default='test')
    p.add_argument('--title-col', default='title')
    p.add_argument('--text-col', default='text')
    p.add_argument('--label-col', default='label')
    p.add_argument('--out-dir', default='data/news')
    p.add_argument('--max-train', type=int, default=None)
    p.add_argument('--max-val', type=int, default=None)
    p.add_argument('--max-test', type=int, default=None)
    args = p.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ds: DatasetDict = load_dataset(args.dataset_name)

    train = _convert_split(ds[args.train_split], args.title_col, args.text_col, args.label_col)
    val = _convert_split(ds[args.val_split], args.title_col, args.text_col, args.label_col)
    test = _convert_split(ds[args.test_split], args.title_col, args.text_col, args.label_col)

    if args.max_train and len(train) > args.max_train:
        train = train.sample(args.max_train, random_state=42).reset_index(drop=True)
    if args.max_val and len(val) > args.max_val:
        val = val.sample(args.max_val, random_state=42).reset_index(drop=True)
    if args.max_test and len(test) > args.max_test:
        test = test.sample(args.max_test, random_state=42).reset_index(drop=True)

    train.to_csv(out / 'train.csv', index=False)
    val.to_csv(out / 'val.csv', index=False)
    test.to_csv(out / 'test.csv', index=False)

    print(f'Saved dataset to {out}')
    print(f'train={len(train)}, val={len(val)}, test={len(test)}')
    print('Label counts:')
    print(' train', train['label'].value_counts().to_dict())
    print(' val  ', val['label'].value_counts().to_dict())
    print(' test ', test['label'].value_counts().to_dict())


if __name__ == '__main__':
    main()
