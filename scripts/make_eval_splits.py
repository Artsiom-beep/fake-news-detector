import argparse
import json
import re
from pathlib import Path


def normalize_text(text: str) -> str:
    text = re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def base_id(case: dict) -> str:
    if case.get("claim_family_id"):
        return str(case["claim_family_id"])
    return str(case.get("id", "")).replace("_p1", "")


def dedup_group(items):
    seen = set()
    out = []
    for item in items:
        key = normalize_text(item.get("text", ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def main(src_path: str, out_dir: str):
    rows = [json.loads(line) for line in Path(src_path).read_text(encoding="utf-8").splitlines() if line.strip()]

    groups = {}
    for row in rows:
        groups.setdefault(base_id(row), []).append(row)

    for key in list(groups.keys()):
        groups[key] = dedup_group(groups[key])

    keys = sorted(
        groups.keys(),
        key=lambda key: (
            min((item.get("published_at", "9999-99-99") or "9999-99-99") for item in groups[key]),
            key,
        ),
    )

    n = len(keys)
    n_dev = max(1, int(n * 0.4))
    n_test = max(1, int(n * 0.3))

    dev_keys = set(keys[:n_dev])
    test_keys = set(keys[n_dev : n_dev + n_test])
    para_keys = set(keys[n_dev + n_test :])

    dev, test, paraphrase = [], [], []
    for key, items in groups.items():
        if key in dev_keys:
            dev.extend(items)
        elif key in test_keys:
            test.extend(items)
        elif key in para_keys:
            paraphrase.extend(items)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "dev.jsonl").write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in dev), encoding="utf-8")
    (out_path / "test.jsonl").write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in test), encoding="utf-8")
    (out_path / "paraphrase_test.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in paraphrase),
        encoding="utf-8",
    )

    print({"dev": len(dev), "test": len(test), "paraphrase_test": len(paraphrase), "groups": n})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default="data/factcheck/versions/eval_cases_v3_60.jsonl")
    parser.add_argument("--out-dir", default="data/factcheck/splits")
    args = parser.parse_args()
    main(args.src, args.out_dir)
