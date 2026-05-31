import json
from pathlib import Path
from typing import List, Dict

SEED_PATH = Path("data/factcheck/seed_evidence.jsonl")


def load_seed() -> List[Dict]:
    if not SEED_PATH.exists():
        return []
    out = []
    for line in SEED_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def search_seed(claim: str, top_k: int = 5) -> List[Dict]:
    c = (claim or "").lower()
    scored = []
    for item in load_seed():
        kws = item.get("keywords", [])
        score = sum(1 for k in kws if str(k).lower() in c)
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for _, it in scored[:top_k]:
        out.append({
            "title": it.get("topic", "seed evidence"),
            "url": it.get("url", "seed://local"),
            "snippet": it.get("text", ""),
            "content": it.get("text", ""),
            "source": it.get("source", "seed"),
        })
    return out
