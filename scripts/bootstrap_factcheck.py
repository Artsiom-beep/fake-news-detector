import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from factcheck.cache import get_cache
from factcheck.config import build_config
from factcheck.service import run_factcheck


def main(warm_nli: bool):
    cache = get_cache()
    cache.set("bootstrap", "status", {"ready": True})
    config = build_config(fast_mode=not warm_nli)
    if warm_nli:
        run_factcheck(text="Reuters reported Google tested search-result changes in the EU.", fast_mode=False, config=config)
    print({"cache": str(cache.path), "pipeline_version": config.pipeline_version, "warm_nli": warm_nli})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--warm-nli", action="store_true")
    args = parser.parse_args()
    main(args.warm_nli)
