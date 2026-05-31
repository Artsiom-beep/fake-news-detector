import argparse
from pathlib import Path
import pandas as pd
from sklearn.model_selection import train_test_split


def main(input_csv: str, out_dir: str, test_size: float, val_size: float, seed: int):
    df = pd.read_csv(input_csv).fillna('')

    # leakage guard: group by content signature so near-duplicates stay in one split
    if 'group_id' not in df.columns:
        df['group_id'] = (df['text'].astype(str).str[:200] + '|' + df['image_path'].astype(str) + '|' + df['video_path'].astype(str)).factorize()[0]

    group_df = df[['group_id', 'label']].drop_duplicates('group_id')

    g_train, g_temp = train_test_split(
        group_df,
        test_size=test_size + val_size,
        random_state=seed,
        stratify=group_df['label'] if group_df['label'].nunique() > 1 else None,
    )

    rel_test = test_size / (test_size + val_size)
    g_val, g_test = train_test_split(
        g_temp,
        test_size=rel_test,
        random_state=seed,
        stratify=g_temp['label'] if g_temp['label'].nunique() > 1 else None,
    )

    train = df[df['group_id'].isin(g_train['group_id'])].drop(columns=['group_id'])
    val = df[df['group_id'].isin(g_val['group_id'])].drop(columns=['group_id'])
    test = df[df['group_id'].isin(g_test['group_id'])].drop(columns=['group_id'])

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    train.to_csv(out / 'train.csv', index=False)
    val.to_csv(out / 'val.csv', index=False)
    test.to_csv(out / 'test.csv', index=False)

    print(f'Saved: train={len(train)}, val={len(val)}, test={len(test)}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--out-dir', default='data')
    p.add_argument('--test-size', type=float, default=0.15)
    p.add_argument('--val-size', type=float, default=0.15)
    p.add_argument('--seed', type=int, default=42)
    args = p.parse_args()
    main(args.input, args.out_dir, args.test_size, args.val_size, args.seed)
