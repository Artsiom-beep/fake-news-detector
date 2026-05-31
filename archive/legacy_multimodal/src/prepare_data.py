import argparse
import pandas as pd


def normalize_text(s: str) -> str:
    s = str(s).replace('\n', ' ').replace('\t', ' ').strip()
    return ' '.join(s.split())


def main(inp: str, out: str):
    df = pd.read_csv(inp)
    for c in ['text', 'transcript', 'image_path', 'video_path']:
        if c not in df.columns:
            df[c] = ''
    if 'label' not in df.columns:
        raise ValueError('Input CSV must contain label column (0/1).')

    df = df[['label', 'text', 'image_path', 'video_path', 'transcript']].copy()
    df['text'] = df['text'].apply(normalize_text)
    df['transcript'] = df['transcript'].apply(normalize_text)
    df = df.drop_duplicates(subset=['label', 'text', 'image_path', 'video_path', 'transcript'])
    df = df[df['label'].isin([0, 1])]

    df.to_csv(out, index=False)
    print(f'Saved cleaned dataset: {out} | rows={len(df)}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    main(args.input, args.output)
