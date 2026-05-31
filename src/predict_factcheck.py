import argparse
import json
import sys

try:
    from .factcheck.service import run_factcheck
except ImportError:
    from factcheck.service import run_factcheck


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run the best-accuracy fact-check and news credibility pipeline")
    parser.add_argument("--text", default="")
    parser.add_argument("--url", default="")
    args = parser.parse_args()

    result = run_factcheck(text=args.text.strip(), url=args.url.strip())
    print(json.dumps(result.to_public_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
