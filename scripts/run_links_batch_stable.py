import json
import time

from _factcheck_eval_adapter import fetch_article_text, run_factcheck_eval_view, set_fast_mode

URLS = [
    "https://www.reuters.com/fact-check/ukraine-depot-blast-video-falsely-implied-show-iran-striking-israeli-nuclear-2026-03-05/",
    "https://factcheck.afp.com/doc.afp.com.99HR8G4",
    "https://newschecker.in/fact-check/video-claiming-to-show-iran-striking-israeli-nuclear-site-is-from-2017-blaze-at-ukrainian-arms-depot",
    "https://www.boomlive.in/fact-check/fake-news-viral-video-iran-airstrikes-israel-nuclear-reactor-old-video-ukraine-factcheck-30790",
]


def main():
    set_fast_mode(True)

    # Warm-up once so we don't pay model-init cost per URL.
    _ = run_factcheck_eval_view("This is a warmup claim about a generic tech news event.")

    results = []
    for url in URLS:
        t0 = time.time()
        try:
            text = fetch_article_text(url, timeout=8)
            if not text:
                item = {"url": url, "status": "fetch_fail", "elapsed_s": round(time.time() - t0, 2)}
            else:
                out = run_factcheck_eval_view(text[:5000])
                item = {
                    "url": url,
                    "status": "ok",
                    "verdict": out.get("article_verdict"),
                    "confidence": out.get("confidence"),
                    "claims": out.get("claims_summary"),
                    "evidence": out.get("evidence_summary"),
                    "elapsed_s": round(time.time() - t0, 2),
                }
        except Exception as e:
            item = {"url": url, "status": "error", "error": str(e), "elapsed_s": round(time.time() - t0, 2)}

        results.append(item)
        print(json.dumps(item, ensure_ascii=False))

    out_path = Path("outputs/factcheck_runs/fake_links_stable_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
