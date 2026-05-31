from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from factcheck.cache import get_cache
from factcheck.config import build_config
from factcheck.ingest import fetch_url_text, is_likely_article_url
from factcheck.retrieval import search_web
from factcheck.service import run_factcheck
from factcheck.source_registry import classify_source


DISCOVERY_QUERIES: dict[str, list[str]] = {
    "politifact.com": [
        "masks covid site:politifact.com",
        "election fraud site:politifact.com",
        "tax rate free world site:politifact.com",
        "facebook posts fake site:politifact.com",
        "climate change site:politifact.com",
        "social security site:politifact.com",
    ],
    "leadstories.com": [
        "fake video site:leadstories.com",
        "fake post site:leadstories.com",
        "did not post site:leadstories.com",
        "AI image site:leadstories.com",
        "no evidence site:leadstories.com",
    ],
    "checkyourfact.com": [
        "fact check false claim site:checkyourfact.com",
        "viral X post site:checkyourfact.com",
        "no did not site:checkyourfact.com",
        "USAID funding site:checkyourfact.com",
        "Iranian general site:checkyourfact.com",
    ],
    "factcheck.org": [
        "false claim site:factcheck.org",
        "covid vaccine site:factcheck.org",
        "voter fraud site:factcheck.org",
        "viral graphic false site:factcheck.org",
    ],
    "snopes.com": [
        "false claim site:snopes.com/fact-check",
        "death hoax site:snopes.com/fact-check",
        "voting ballots site:snopes.com/fact-check",
    ],
    "fullfact.org": [
        "false claim site:fullfact.org",
        "covid vaccine site:fullfact.org",
        "what was claimed site:fullfact.org",
    ],
    "africacheck.org": [
        "false claim site:africacheck.org/fact-checks",
        "hoax scam site:africacheck.org/fact-checks",
    ],
    "factcheck.afp.com": [
        "fake video site:factcheck.afp.com",
        "false claim site:factcheck.afp.com",
    ],
    "boomlive.in": [
        "fake news viral video site:boomlive.in",
        "fact check false site:boomlive.in",
    ],
    "newschecker.in": [
        "fact check viral video site:newschecker.in",
        "false claim site:newschecker.in",
    ],
}


MANUAL_SEED_URLS = [
    {
        "url": "https://www.politifact.com/factchecks/2020/may/21/facebook-posts/disposable-homemade-masks-are-effective-stopping-a",
        "origin": "manual_seed:existing_smoke",
    },
    {
        "url": "https://www.snopes.com/fact-check/cher-death-hoax/",
        "origin": "manual_seed:web_search_snopes",
    },
    {
        "url": "https://www.snopes.com/fact-check/poll-workers-writing-on-ballots/",
        "origin": "manual_seed:web_search_snopes",
    },
    {
        "url": "https://www.snopes.com/fact-check/simpsons-predict-titanic-submersible/",
        "origin": "manual_seed:web_search_snopes",
    },
    {
        "url": "https://www.factcheck.org/2025/06/viral-graphic-makes-false-questionable-claims-about-house-reconciliation-bill/",
        "origin": "manual_seed:web_search_factcheck_org",
    },
    {
        "url": "https://www.factcheck.org/2025/08/factchecking-trumps-claims-about-mail-in-ballots-voting-machines-and-states-role/",
        "origin": "manual_seed:web_search_factcheck_org",
    },
    {
        "url": "https://www.factcheck.org/2024/10/floridas-2024-2025-covid-19-vaccine-guidance-misunderstands-distorts-existing-science/",
        "origin": "manual_seed:web_search_factcheck_org",
    },
    {
        "url": "https://africacheck.org/fact-checks/spotchecks/hoaxes-scams-and-half-truths",
        "origin": "manual_seed:web_search_africa_check",
    },
    {
        "url": "https://factcheck.afp.com/doc.afp.com.99HR8G4",
        "origin": "manual_seed:legacy_fake_links_test",
    },
    {
        "url": "https://newschecker.in/fact-check/video-claiming-to-show-iran-striking-israeli-nuclear-site-is-from-2017-blaze-at-ukrainian-arms-depot",
        "origin": "manual_seed:legacy_fake_links_test",
    },
    {
        "url": "https://www.boomlive.in/fact-check/fake-news-viral-video-iran-airstrikes-israel-nuclear-reactor-old-video-ukraine-factcheck-30790",
        "origin": "manual_seed:legacy_fake_links_test",
    },
    {
        "url": "https://www.reuters.com/fact-check/ukraine-depot-blast-video-falsely-implied-show-iran-striking-israeli-nuclear-2026-03-05/",
        "origin": "manual_seed:research_excluded_reuters_fact_check",
    },
]


POLICY_UNCERTAIN_CASES = [
    {
        "id": "unknown_001",
        "case_type": "unknown_text",
        "text": "A totally new unverified claim with no known fact-check page.",
        "expected": "uncertain",
        "expected_source": "policy_unknown_claim",
        "source_domain": "synthetic.local",
        "source_url": "",
    },
    {
        "id": "unknown_002",
        "case_type": "unknown_text",
        "text": "The claim has no reliable source and cannot be verified yet.",
        "expected": "uncertain",
        "expected_source": "policy_low_specificity_meta_claim",
        "source_domain": "synthetic.local",
        "source_url": "",
    },
    {
        "id": "unknown_003",
        "case_type": "unknown_text",
        "text": "An anonymous Telegram channel says a secret law was signed yesterday, but gives no document number.",
        "expected": "uncertain",
        "expected_source": "policy_unknown_claim",
        "source_domain": "synthetic.local",
        "source_url": "",
    },
    {
        "id": "unknown_004",
        "case_type": "unknown_text",
        "text": "A viral post claims every school in Europe will ban paper books next week.",
        "expected": "uncertain",
        "expected_source": "policy_unknown_claim",
        "source_domain": "synthetic.local",
        "source_url": "",
    },
    {
        "id": "unknown_005",
        "case_type": "unknown_text",
        "text": "A forum post says a new unnamed vaccine ingredient was added worldwide without public notice.",
        "expected": "uncertain",
        "expected_source": "policy_unknown_claim",
        "source_domain": "synthetic.local",
        "source_url": "",
    },
    {
        "id": "badurl_001",
        "case_type": "bad_or_listing_url",
        "url": "https://www.politifact.com/search/?q=covid",
        "expected": "uncertain",
        "expected_source": "policy_listing_url",
        "source_domain": "politifact.com",
        "source_url": "https://www.politifact.com/search/?q=covid",
    },
    {
        "id": "badurl_002",
        "case_type": "bad_or_listing_url",
        "url": "https://leadstories.com/cgi-bin/mt/mt-search.fcgi?IncludeBlogs=1&archive_type=Index&page=3",
        "expected": "uncertain",
        "expected_source": "policy_listing_url",
        "source_domain": "leadstories.com",
        "source_url": "https://leadstories.com/cgi-bin/mt/mt-search.fcgi?IncludeBlogs=1&archive_type=Index&page=3",
    },
    {
        "id": "badurl_003",
        "case_type": "bad_or_listing_url",
        "url": "https://www.reuters.com/world/",
        "expected": "uncertain",
        "expected_source": "policy_listing_url",
        "source_domain": "reuters.com",
        "source_url": "https://www.reuters.com/world/",
    },
]


def _expected_from_explicit(verdict: str) -> str:
    if verdict == "support":
        return "true"
    if verdict == "refute":
        return "fake"
    return "uncertain"


def _safe_id(text: str, fallback: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in text)[:80].strip("_")
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or fallback


def _domain_of(url: str) -> str:
    return classify_source(url).domain or "unknown"


def _discover_source_pages(max_pages_per_domain: int, search_count: int) -> list[dict[str, Any]]:
    cache = get_cache()
    found: dict[str, dict[str, Any]] = {}

    def add_url(url: str, origin: str) -> None:
        if not url or url in found:
            return
        profile = classify_source(url)
        if profile.source_type not in {"factcheck_org", "primary_news"}:
            return
        payload = fetch_url_text(url, cache=cache)
        final_url = payload.get("url", url)
        final_profile = classify_source(final_url)
        if final_url in found:
            return
        found[final_url] = {
            "url": final_url,
            "source_domain": final_profile.domain or profile.domain or _domain_of(final_url),
            "source_type": final_profile.source_type,
            "source_trust": final_profile.trust,
            "title": payload.get("title", ""),
            "claim_text": payload.get("claim_text", ""),
            "ruling_text": payload.get("ruling_text", ""),
            "explicit_verdict": payload.get("explicit_verdict", ""),
            "explicit_verdict_label": payload.get("explicit_verdict_label", ""),
            "verdict_source": payload.get("verdict_source", ""),
            "is_factcheck_article": bool(payload.get("is_factcheck_article", False)),
            "fetch_source": payload.get("fetch_source", ""),
            "origin": origin,
        }

    for seed in MANUAL_SEED_URLS:
        add_url(seed["url"], seed["origin"])

    domain_counts = Counter(page["source_domain"] for page in found.values())
    for domain, queries in DISCOVERY_QUERIES.items():
        if domain_counts[domain] >= max_pages_per_domain:
            continue
        for query in queries:
            if domain_counts[domain] >= max_pages_per_domain:
                break
            for hit in search_web(query, count=search_count, cache=cache):
                url = hit.get("url", "")
                if domain not in url:
                    continue
                if not is_likely_article_url(url):
                    continue
                before = len(found)
                add_url(url, f"live_search:{query}")
                if len(found) > before:
                    domain_counts[domain] += 1
                    if domain_counts[domain] >= max_pages_per_domain:
                        break

    return list(found.values())


def _build_cases(pages: list[dict[str, Any]], max_text_cases: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()

    for page in pages:
        expected = _expected_from_explicit(page.get("explicit_verdict", ""))
        if page.get("explicit_verdict"):
            case_type = "direct_url_explicit"
            expected_source = "parsed_explicit_verdict_from_source_page"
        else:
            case_type = "direct_url_no_explicit"
            expected_source = "policy_no_explicit_factcheck_verdict"
            expected = "uncertain"

        counters[case_type] += 1
        cases.append(
            {
                "id": f"{case_type}_{counters[case_type]:03d}_{_safe_id(page.get('source_domain', ''), 'source')}",
                "case_type": case_type,
                "url": page["url"],
                "text": "",
                "expected": expected,
                "expected_source": expected_source,
                "source_domain": page.get("source_domain", ""),
                "source_type": page.get("source_type", ""),
                "source_url": page["url"],
                "source_title": page.get("title", ""),
                "source_claim": page.get("claim_text", ""),
                "source_explicit_verdict": page.get("explicit_verdict", ""),
                "source_verdict_label": page.get("explicit_verdict_label", ""),
                "source_origin": page.get("origin", ""),
            }
        )

    text_added = 0
    for page in pages:
        if text_added >= max_text_cases:
            break
        expected = _expected_from_explicit(page.get("explicit_verdict", ""))
        claim_text = (page.get("claim_text") or page.get("title") or "").strip()
        if expected not in {"true", "fake"}:
            continue
        if len(claim_text.split()) < 5:
            continue
        text_added += 1
        cases.append(
            {
                "id": f"text_claim_{text_added:03d}_{_safe_id(page.get('source_domain', ''), 'source')}",
                "case_type": "text_from_factcheck_claim",
                "url": "",
                "text": claim_text,
                "expected": expected,
                "expected_source": "parsed_explicit_verdict_from_source_page",
                "source_domain": page.get("source_domain", ""),
                "source_type": page.get("source_type", ""),
                "source_url": page["url"],
                "source_title": page.get("title", ""),
                "source_claim": page.get("claim_text", ""),
                "source_explicit_verdict": page.get("explicit_verdict", ""),
                "source_verdict_label": page.get("explicit_verdict_label", ""),
                "source_origin": page.get("origin", ""),
            }
        )

    cases.extend(POLICY_UNCERTAIN_CASES)
    return cases


def _run_case_worker(case: dict[str, Any], queue: mp.Queue) -> None:
    try:
        result = run_factcheck(
            text=(case.get("text") or "").strip(),
            url=(case.get("url") or "").strip(),
            fast_mode=True,
            mode="factcheck_only",
        ).to_public_dict()
        evidence = result.get("evidence", [])
        queue.put(
            {
                "id": case["id"],
                "case_type": case["case_type"],
                "expected": case["expected"],
                "pred": result.get("verdict", "uncertain"),
                "confidence": result.get("confidence", 0.0),
                "claim": result.get("claim", ""),
                "summary": result.get("summary", ""),
                "evidence_count": len(evidence),
                "evidence_urls": [item.get("url", "") for item in evidence],
                "evidence_domains": [item.get("domain", "") for item in evidence],
                "evidence_stances": [item.get("stance", "") for item in evidence],
                "fallbacks_used": result.get("trace", {}).get("fallbacks_used", []),
                "decision_reasons": result.get("trace", {}).get("decision_reasons", []),
                "queries_count": len(result.get("trace", {}).get("queries", [])),
                "filtered_count": len(result.get("trace", {}).get("filtered_urls", [])),
                "timings_ms": result.get("trace", {}).get("stage_timings_ms", {}),
            }
        )
    except Exception as exc:
        queue.put(
            {
                "id": case["id"],
                "case_type": case["case_type"],
                "expected": case["expected"],
                "pred": "error",
                "confidence": 0.0,
                "error": repr(exc),
            }
        )


def _run_case(case: dict[str, Any], timeout: int) -> dict[str, Any]:
    queue: mp.Queue = mp.Queue()
    process = mp.Process(target=_run_case_worker, args=(case, queue), daemon=True)
    process.start()
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(2)
        return {
            "id": case["id"],
            "case_type": case["case_type"],
            "expected": case["expected"],
            "pred": "timeout",
            "confidence": 0.0,
        }
    if queue.empty():
        return {
            "id": case["id"],
            "case_type": case["case_type"],
            "expected": case["expected"],
            "pred": "error",
            "confidence": 0.0,
            "error": "worker returned no result",
        }
    return queue.get()


def _aggregate(cases: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    case_by_id = {case["id"]: case for case in cases}
    n = len(results)
    pred_counts = Counter(item.get("pred", "other") for item in results)
    hard = [item for item in results if item.get("pred") in {"true", "fake"}]
    hard_correct = [item for item in hard if item.get("pred") == item.get("expected")]
    false_hard = [item for item in hard if item.get("expected") == "uncertain"]
    mismatches = [item for item in results if item.get("pred") != item.get("expected")]
    errors = [item for item in results if item.get("pred") in {"error", "timeout"}]

    def breakdown(field: str) -> dict[str, dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in results:
            case = case_by_id.get(item["id"], {})
            buckets[str(case.get(field, "unknown"))].append(item)
        payload: dict[str, dict[str, Any]] = {}
        for key, rows in sorted(buckets.items()):
            hard_rows = [row for row in rows if row.get("pred") in {"true", "fake"}]
            hard_correct_rows = [row for row in hard_rows if row.get("pred") == row.get("expected")]
            payload[key] = {
                "n": len(rows),
                "accuracy": sum(row.get("pred") == row.get("expected") for row in rows) / max(len(rows), 1),
                "uncertain_rate": sum(row.get("pred") == "uncertain" for row in rows) / max(len(rows), 1),
                "hard_count": len(hard_rows),
                "hard_precision": len(hard_correct_rows) / max(len(hard_rows), 1) if hard_rows else None,
                "errors": sum(row.get("pred") in {"error", "timeout"} for row in rows),
            }
        return payload

    return {
        "n": n,
        "accuracy": sum(item.get("pred") == item.get("expected") for item in results) / max(n, 1),
        "uncertain_rate": pred_counts.get("uncertain", 0) / max(n, 1),
        "error_rate": len(errors) / max(n, 1),
        "hard_count": len(hard),
        "hard_verdict_precision": len(hard_correct) / max(len(hard), 1) if hard else None,
        "false_hard_verdicts": len(false_hard),
        "predictions": dict(pred_counts),
        "by_case_type": breakdown("case_type"),
        "by_source_domain": breakdown("source_domain"),
        "by_expected_source": breakdown("expected_source"),
        "mismatch_count": len(mismatches),
        "mismatch_ids": [item["id"] for item in mismatches[:50]],
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _format_float(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    metrics = payload["metrics"]
    cases = payload["cases"]
    results = payload["results"]
    case_by_id = {case["id"]: case for case in cases}
    mismatches = [item for item in results if item.get("pred") != item.get("expected")]

    lines = [
        "# FactCheck-Only Stress Test",
        "",
        f"- Run timestamp UTC: `{payload['run_timestamp_utc']}`",
        f"- Mode: `factcheck_only`",
        f"- Dataset: `{payload['dataset_path']}`",
        f"- Results: `{payload['results_path']}`",
        f"- Cases: `{metrics['n']}`",
        "",
        "## Data Sources",
        "",
        "- Live discovery used trusted fact-check site searches over PolitiFact, FactCheck.org, Snopes, Lead Stories, Full Fact, Check Your Fact, Africa Check, AFP Fact Check, BOOM Live and Newschecker.",
        "- Manual seed URLs were added for sources that site-search often misses: AFP Fact Check, BOOM Live, Newschecker, Snopes, FactCheck.org, Africa Check and Reuters fact-check pages.",
        "- Expected labels for `direct_url_explicit` and `text_from_factcheck_claim` cases come from parsed explicit verdict text on the source fact-check page. This tests parser/retrieval/product behavior, not an independent human benchmark.",
        "- Expected labels for unknown/meta/listing cases are policy expectations: they should return `uncertain`.",
        "",
        "## Overall Metrics",
        "",
        f"- Accuracy: `{_format_float(metrics['accuracy'])}`",
        f"- Uncertain rate: `{_format_float(metrics['uncertain_rate'])}`",
        f"- Error rate: `{_format_float(metrics['error_rate'])}`",
        f"- Hard verdict count: `{metrics['hard_count']}`",
        f"- Hard verdict precision: `{_format_float(metrics['hard_verdict_precision'])}`",
        f"- False hard verdicts on expected-uncertain cases: `{metrics['false_hard_verdicts']}`",
        "",
        "## Breakdown By Case Type",
        "",
        "| case_type | n | accuracy | uncertain_rate | hard_count | hard_precision | errors |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, row in metrics["by_case_type"].items():
        lines.append(
            f"| {key} | {row['n']} | {_format_float(row['accuracy'])} | {_format_float(row['uncertain_rate'])} | "
            f"{row['hard_count']} | {_format_float(row['hard_precision'])} | {row['errors']} |"
        )

    lines.extend(
        [
            "",
            "## Breakdown By Source Domain",
            "",
            "| domain | n | accuracy | uncertain_rate | hard_count | hard_precision | errors |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for key, row in metrics["by_source_domain"].items():
        lines.append(
            f"| {key} | {row['n']} | {_format_float(row['accuracy'])} | {_format_float(row['uncertain_rate'])} | "
            f"{row['hard_count']} | {_format_float(row['hard_precision'])} | {row['errors']} |"
        )

    lines.extend(["", "## Mismatches And Failures", ""])
    if not mismatches:
        lines.append("- No mismatches.")
    else:
        for item in mismatches[:40]:
            case = case_by_id.get(item["id"], {})
            lines.append(
                "- "
                f"`{item['id']}` type=`{case.get('case_type')}` domain=`{case.get('source_domain')}` "
                f"expected=`{item.get('expected')}` pred=`{item.get('pred')}` "
                f"conf=`{_format_float(item.get('confidence'))}` "
                f"source=`{case.get('source_url', '')}`"
            )
    lines.extend(
        [
            "",
            "## Source URLs Used",
            "",
        ]
    )
    seen_urls = set()
    for case in cases:
        url = case.get("source_url") or case.get("url") or ""
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        lines.append(f"- {case.get('source_domain', 'unknown')}: {url}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-out", default="data/factcheck/versions/stress_factcheck_only_live_2026_04_18.jsonl")
    parser.add_argument("--results-out", default="outputs/factcheck_runs/stress_factcheck_only_live_2026_04_18.json")
    parser.add_argument("--report-out", default="outputs/factcheck_runs/stress_factcheck_only_live_2026_04_18.md")
    parser.add_argument("--max-pages-per-domain", type=int, default=12)
    parser.add_argument("--search-count", type=int, default=5)
    parser.add_argument("--max-text-cases", type=int, default=60)
    parser.add_argument("--timeout", type=int, default=50)
    args = parser.parse_args()

    started = time.perf_counter()
    pages = _discover_source_pages(
        max_pages_per_domain=max(1, args.max_pages_per_domain),
        search_count=max(1, args.search_count),
    )
    cases = _build_cases(pages, max_text_cases=max(0, args.max_text_cases))
    dataset_path = ROOT / args.dataset_out
    results_path = ROOT / args.results_out
    report_path = ROOT / args.report_out
    _write_jsonl(dataset_path, cases)

    results = []
    for index, case in enumerate(cases, 1):
        item = _run_case(case, timeout=max(5, args.timeout))
        results.append(item)
        print(
            json.dumps(
                {
                    "i": index,
                    "n": len(cases),
                    "id": item.get("id"),
                    "expected": item.get("expected"),
                    "pred": item.get("pred"),
                    "confidence": item.get("confidence"),
                },
                ensure_ascii=False,
            )
        )

    config = build_config(fast_mode=True, mode="factcheck_only")
    payload = {
        "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.perf_counter() - started, 3),
        "pipeline_version": config.pipeline_version,
        "config": config.snapshot().to_dict(),
        "dataset_path": str(dataset_path),
        "results_path": str(results_path),
        "report_path": str(report_path),
        "discovered_pages": pages,
        "cases": cases,
        "results": results,
        "metrics": _aggregate(cases, results),
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(report_path, payload)

    print(
        json.dumps(
            {
                "dataset": str(dataset_path),
                "results": str(results_path),
                "report": str(report_path),
                **payload["metrics"],
            },
            ensure_ascii=False,
            default=str,
        )
    )


if __name__ == "__main__":
    mp.freeze_support()
    main()
