from __future__ import annotations

import argparse
import json
import sys

try:
    from .factcheck.service import run_factcheck
except ImportError:
    from factcheck.service import run_factcheck


def _legacy_label(verdict: str) -> str:
    if verdict == "true":
        return "real"
    if verdict == "fake":
        return "fake"
    return "uncertain"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="Compatibility CLI for the old prototype predictor. Delegates to the canonical Verity Lens engine."
    )
    parser.add_argument("--text", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--transcript", default="", help="Deprecated; appended to --text for compatibility.")
    parser.add_argument("--model-path", default="", help="Deprecated; ignored by the canonical engine.")
    parser.add_argument("--image-path", default="", help="Deprecated; use the UI or /factcheck-image for image checks.")
    parser.add_argument("--video-path", default="", help="Deprecated; video scoring is not part of the current product.")
    parser.add_argument("--text-model", default="", help="Deprecated; ignored by the canonical engine.")
    parser.add_argument("--device", default="", help="Deprecated; ignored by the canonical engine.")
    parser.add_argument("--threshold", default="", help="Deprecated; decision thresholds are managed by the canonical engine.")
    parser.add_argument("--text-only", action="store_true", help="Deprecated; retained so old commands do not crash.")
    args = parser.parse_args(argv)

    text = " ".join(part.strip() for part in (args.text, args.transcript) if part and part.strip())
    result = run_factcheck(text=text, url=args.url.strip())
    payload = result.to_public_dict()
    label = _legacy_label(str(payload.get("verdict", "uncertain")))
    payload.update(
        {
            "label": label,
            "fake_probability": payload.get("confidence", 0.0) if label == "fake" else 0.0,
            "compatibility": "legacy_predict_cli_delegates_to_factcheck",
        }
    )
    if args.image_path or args.video_path:
        payload["compatibility_note"] = (
            "The old multimodal predictor has been removed from the product path. "
            "Use the web UI or /factcheck-image for screenshots and AI-image risk checks."
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
