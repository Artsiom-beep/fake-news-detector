import argparse
from pathlib import Path
import pandas as pd


def load_one(path: str) -> pd.DataFrame:
    df = pd.read_csv(path).fillna('')
    for c in ['label', 'text', 'image_path', 'video_path', 'transcript']:
        if c not in df.columns:
            df[c] = ''
    df = df[['label', 'text', 'image_path', 'video_path', 'transcript']]
    df['label'] = pd.to_numeric(df['label'], errors='coerce').fillna(-1).astype(int)
    df = df[df['label'].isin([0, 1])]
    return df


def main(inputs: list[str], output: str):
    frames = [load_one(p) for p in inputs]
    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=['label', 'text', 'image_path', 'video_path', 'transcript'])

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f'Saved merged manifest: {output} | rows={len(df)}')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--inputs', nargs='+', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    main(args.inputs, args.output)
