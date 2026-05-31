import json
import multiprocessing as mp
import time

from _factcheck_eval_adapter import fetch_article_text, run_factcheck_eval_view, set_fast_mode

URLS = [
    "https://www.reuters.com/fact-check/ukraine-depot-blast-video-falsely-implied-show-iran-striking-israeli-nuclear-2026-03-05/",
    "https://factcheck.afp.com/doc.afp.com.99HR8G4",
    "https://newschecker.in/fact-check/video-claiming-to-show-iran-striking-israeli-nuclear-site-is-from-2017-blaze-at-ukrainian-arms-depot",
    "https://www.boomlive.in/fact-check/fake-news-viral-video-iran-airstrikes-israel-nuclear-reactor-old-video-ukraine-factcheck-30790",
]


def worker(url: str, q: mp.Queue):
    try:
        set_fast_mode(True)
        text = fetch_article_text(url, timeout=8)
        if not text:
            q.put({"url": url, "status": "fetch_fail"})
            return
        out = run_factcheck_eval_view(text[:5000])
        q.put({
            "url": url,
            "status": "ok",
            "verdict": out.get("article_verdict"),
            "confidence": out.get("confidence"),
            "claims": out.get("claims_summary"),
            "evidence": out.get("evidence_summary"),
        })
    except Exception as e:
        q.put({"url": url, "status": "error", "error": str(e)})


def main():
    results = []
    for url in URLS:
        q = mp.Queue()
        p = mp.Process(target=worker, args=(url, q), daemon=True)
        p.start()
        p.join(75)  # hard cap per URL

        if p.is_alive():
            p.terminate()
            p.join(5)
            results.append({"url": url, "status": "timeout"})
            print(f"TIMEOUT\t{url}")
            continue

        if not q.empty():
            item = q.get()
        else:
            item = {"url": url, "status": "error", "error": "no result"}

        results.append(item)
        print(json.dumps(item, ensure_ascii=False))

    out_path = Path("outputs/factcheck_runs/fake_links_safe_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
