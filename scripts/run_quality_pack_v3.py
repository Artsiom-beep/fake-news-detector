from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from factcheck.ingest import canonicalize_url, is_likely_article_url
from factcheck.service import run_factcheck
from factcheck.source_registry import classify_source


@dataclass(frozen=True)
class FeedSource:
    id: str
    name: str
    url: str
    expected_case_type: str = "trusted_news_article"
    expected_min_label: str = "medium"


FEED_SOURCES = [
    FeedSource("bbc_world", "BBC World RSS", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    FeedSource("npr_news", "NPR News RSS", "https://feeds.npr.org/1001/rss.xml"),
    FeedSource("guardian_world", "The Guardian World RSS", "https://www.theguardian.com/world/rss"),
    FeedSource("aljazeera_all", "Al Jazeera RSS", "https://www.aljazeera.com/xml/rss/all.xml"),
    FeedSource("cbs_latest", "CBS News latest RSS", "https://www.cbsnews.com/latest/rss/main"),
    FeedSource("nbc_news", "NBC News RSS", "https://feeds.nbcnews.com/nbcnews/public/news"),
    FeedSource("dw_all", "DW RSS", "https://rss.dw.com/rdf/rss-en-all"),
    FeedSource("france24_en", "France24 RSS", "https://www.france24.com/en/rss"),
    FeedSource("abc_top", "ABC News top stories RSS", "https://abcnews.go.com/abcnews/topstories"),
    FeedSource("sky_world", "Sky News world RSS", "https://feeds.skynews.com/feeds/rss/world.xml"),
    FeedSource("ap_top", "AP News top news RSS", "https://apnews.com/hub/ap-top-news?output=rss"),
]


STATIC_CASES = [
    {
        "id": "guardrail_bbc_listing",
        "url": "https://www.bbc.com/news",
        "source_name": "BBC listing page",
        "collection_source": "manual_guardrail",
        "case_type": "listing_guardrail",
        "expected": {"allowed_labels": ["unknown", "low"], "max_score": 0.49},
        "notes": "Listing pages should not receive high credibility.",
    },
    {
        "id": "guardrail_reuters_home",
        "url": "https://www.reuters.com/",
        "source_name": "Reuters homepage",
        "collection_source": "manual_guardrail",
        "case_type": "listing_guardrail",
        "expected": {"allowed_labels": ["unknown", "low"], "max_score": 0.49},
        "notes": "Homepages should not be treated as direct article evidence.",
    },
    {
        "id": "guardrail_medium_home",
        "url": "https://medium.com/",
        "source_name": "Medium homepage",
        "collection_source": "manual_guardrail",
        "case_type": "low_trust_guardrail",
        "expected": {"allowed_labels": ["unknown", "low"], "max_score": 0.49},
        "notes": "Low-trust/wrapper-like pages should not score high without corroboration.",
    },
    {
        "id": "guardrail_youtube_video",
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "source_name": "YouTube video",
        "collection_source": "manual_guardrail",
        "case_type": "social_guardrail",
        "expected": {"allowed_labels": ["unknown", "low"], "max_score": 0.49},
        "notes": "Social/video URLs should not be scored as high-confidence news articles.",
    },
    {
        "id": "factcheck_politifact_false_masks",
        "url": "https://www.politifact.com/factchecks/2020/may/21/facebook-posts/disposable-homemade-masks-are-effective-stopping-a",
        "source_name": "PolitiFact fact-check",
        "collection_source": "manual_factcheck_seed",
        "case_type": "factcheck_url",
        "expected": {"allowed_verdicts": ["fake"]},
        "notes": "Known explicit fact-check page should produce a hard verdict.",
    },
    {
        "id": "simple_true_arithmetic",
        "text": "100 is lower than 200",
        "source_name": "Local simple-fact smoke",
        "collection_source": "manual_simple_fact",
        "case_type": "simple_fact",
        "expected": {"allowed_verdicts": ["true"]},
        "notes": "Internal simple facts remain part of best_accuracy.",
    },
    {
        "id": "simple_false_taste",
        "text": "Salt is sweet",
        "source_name": "Local simple-fact smoke",
        "collection_source": "manual_simple_fact",
        "case_type": "simple_fact",
        "expected": {"allowed_verdicts": ["fake"]},
        "notes": "Internal simple facts remain part of best_accuracy.",
    },
]

LABEL_RANK = {"unknown": 0, "low": 1, "medium": 2, "high": 3}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fetch_feed(source: FeedSource, per_source: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    meta = {
        "id": source.id,
        "name": source.name,
        "source_url": source.url,
        "fetched_at": _now_iso(),
        "status": "ok",
        "error": "",
        "items_collected": 0,
    }
    response = None
    try:
        response = requests.get(source.url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception as exc:
        if response is not None and response.text:
            cases = _extract_cases_from_html(source, response.text, per_source)
            if cases:
                meta["status"] = "html_fallback"
                meta["error"] = str(exc)
                meta["items_collected"] = len(cases)
                return cases, meta
        meta["status"] = "error"
        meta["error"] = str(exc)
        return [], meta

    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not link:
            guid = item.findtext("guid") or ""
            link = guid.strip() if guid.startswith("http") else ""
        url = canonicalize_url(link)
        if not url or url in seen or not is_likely_article_url(url):
            continue
        seen.add(url)
        case_type, expected, notes = _feed_case_type_and_expected(title, url, source)
        cases.append(
            {
                "id": f"{source.id}_{len(cases) + 1:02d}",
                "url": url,
                "title": title,
                "source_name": source.name,
                "collection_source": source.url,
                "case_type": case_type,
                "expected": expected,
                "notes": notes,
            }
        )
        if len(cases) >= per_source:
            break
    meta["items_collected"] = len(cases)
    return cases, meta


def _extract_cases_from_html(source: FeedSource, html: str, per_source: int) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    source_host = canonicalize_url(source.url).split("//", 1)[-1].split("/", 1)[0]
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        if href.startswith("/"):
            href = f"https://{source_host}{href}"
        url = canonicalize_url(href)
        if not url or url in seen or not is_likely_article_url(url):
            continue
        if classify_source(url).domain != classify_source(source.url).domain:
            continue
        title = anchor.get_text(" ", strip=True)
        case_type, expected, notes = _feed_case_type_and_expected(title, url, source)
        seen.add(url)
        cases.append(
            {
                "id": f"{source.id}_{len(cases) + 1:02d}",
                "url": url,
                "title": title,
                "source_name": source.name,
                "collection_source": source.url,
                "case_type": case_type,
                "expected": expected,
                "notes": notes + " HTML fallback used because feed XML was unavailable or invalid.",
            }
        )
        if len(cases) >= per_source:
            break
    return cases


def _feed_case_type_and_expected(title: str, url: str, source: FeedSource) -> tuple[str, dict[str, Any], str]:
    low = f"{title} {url}".lower()
    media_markers = ("photos:", "photo:", "pictures", "week in pictures", "/video/", "/videos/")
    if any(marker in low for marker in media_markers):
        return (
            "trusted_media_article",
            {"min_label": "low"},
            "Collected from publisher RSS feed; media/gallery item, so low+ is acceptable.",
        )
    return (
        source.expected_case_type,
        {"min_label": source.expected_min_label},
        "Collected from publisher RSS feed.",
    )


def collect_cases(per_source: int, max_cases: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cases = list(STATIC_CASES)
    feed_meta: list[dict[str, Any]] = []
    seen_urls = {canonicalize_url(item.get("url", "")) for item in cases if item.get("url")}
    for source in FEED_SOURCES:
        feed_cases, meta = _fetch_feed(source, per_source=per_source)
        feed_meta.append(meta)
        for case in feed_cases:
            url = canonicalize_url(case.get("url", ""))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            cases.append(case)
            if len(cases) >= max_cases:
                return cases, feed_meta
    return cases[:max_cases], feed_meta


def _expected_pass(case: dict[str, Any], payload: dict[str, Any]) -> tuple[bool, list[str]]:
    expected = case.get("expected", {}) or {}
    issues: list[str] = []
    verdict = payload.get("verdict", "uncertain")
    credibility = payload.get("credibility") or {}
    label = credibility.get("label")
    score = float(credibility.get("score", payload.get("confidence", 0.0)) or 0.0)

    allowed_verdicts = expected.get("allowed_verdicts")
    if allowed_verdicts and verdict not in allowed_verdicts:
        issues.append(f"verdict={verdict} not in {allowed_verdicts}")

    allowed_labels = expected.get("allowed_labels")
    if allowed_labels and label not in allowed_labels:
        issues.append(f"label={label} not in {allowed_labels}")

    min_label = expected.get("min_label")
    if min_label and LABEL_RANK.get(label or "unknown", 0) < LABEL_RANK[min_label]:
        issues.append(f"label={label} below {min_label}")

    max_score = expected.get("max_score")
    if max_score is not None and score > float(max_score):
        issues.append(f"score={score:.3f} above max {float(max_score):.3f}")

    if case.get("case_type") in {"trusted_news_article", "trusted_media_article"}:
        if payload.get("verdict") != "uncertain":
            issues.append("ordinary news produced hard verdict")
        if not payload.get("credibility"):
            issues.append("ordinary news missing credibility payload")

    if case.get("case_type") == "factcheck_url" and verdict == "uncertain":
        issues.append("fact-check URL did not produce hard verdict")

    claim = payload.get("claim", "")
    if " | " in claim or " - BBC" in claim or " - AP" in claim:
        issues.append("claim appears to contain publisher boilerplate")

    for evidence in payload.get("evidence", [])[:5]:
        url = evidence.get("url", "")
        domain = evidence.get("domain", "")
        if url.rstrip("/") in {f"https://{domain}", f"https://www.{domain}"}:
            issues.append(f"root evidence URL for {domain}")
    return not issues, issues


def _run_case(case: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    row = {
        "id": case.get("id", ""),
        "case_type": case.get("case_type", ""),
        "source_name": case.get("source_name", ""),
        "collection_source": case.get("collection_source", ""),
        "url": case.get("url", ""),
        "text": case.get("text", ""),
        "title": case.get("title", ""),
        "expected": case.get("expected", {}),
        "notes": case.get("notes", ""),
        "status": "ok",
        "error": "",
    }
    try:
        result = run_factcheck(text=case.get("text", ""), url=case.get("url", "")).to_public_dict()
        passed, issues = _expected_pass(case, result)
        credibility = result.get("credibility") or {}
        profile = classify_source(case.get("url", ""))
        row.update(
            {
                "passed": passed,
                "issues": issues,
                "source_domain": profile.domain,
                "source_type": profile.source_type,
                "source_trust": profile.trust,
                "verdict": result.get("verdict"),
                "confidence": result.get("confidence"),
                "claim": result.get("claim"),
                "summary": result.get("summary"),
                "credibility_score": credibility.get("score"),
                "credibility_label": credibility.get("label"),
                "source_score": credibility.get("source_score"),
                "article_quality_score": credibility.get("article_quality_score"),
                "corroboration_score": credibility.get("corroboration_score"),
                "risk_score": credibility.get("risk_score"),
                "matched_sources": credibility.get("matched_sources", []),
                "risk_flags": credibility.get("risk_flags", []),
                "evidence_count": len(result.get("evidence", [])),
                "evidence": result.get("evidence", [])[:6],
                "fallbacks": result.get("trace", {}).get("fallbacks_used", []),
                "queries": result.get("trace", {}).get("queries", [])[:12],
                "stage_timings_ms": result.get("trace", {}).get("stage_timings_ms", {}),
                "pipeline_version": result.get("pipeline_version", ""),
            }
        )
    except Exception as exc:
        row.update({"status": "error", "passed": False, "error": repr(exc), "issues": [repr(exc)]})
    row["runtime_sec"] = round(time.perf_counter() - started, 3)
    return row


def _summarize(rows: list[dict[str, Any]], feed_meta: list[dict[str, Any]]) -> dict[str, Any]:
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    return {
        "created_at": _now_iso(),
        "dataset_version": "quality_pack_v3_live",
        "pipeline_version": rows[0].get("pipeline_version", "") if rows else "",
        "total": len(rows),
        "ok": len(ok_rows),
        "errors": len(rows) - len(ok_rows),
        "passed": sum(1 for row in rows if row.get("passed")),
        "failed": sum(1 for row in rows if not row.get("passed")),
        "by_case_type": dict(Counter(row.get("case_type", "") for row in rows)),
        "by_source_type": dict(Counter(row.get("source_type", "") for row in ok_rows)),
        "by_credibility_label": dict(Counter(row.get("credibility_label") or "none" for row in ok_rows)),
        "by_verdict": dict(Counter(row.get("verdict") or "none" for row in ok_rows)),
        "feed_sources": feed_meta,
    }


def _markdown_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    failed = [row for row in rows if not row.get("passed")]
    slow = sorted(rows, key=lambda row: float(row.get("runtime_sec", 0.0)), reverse=True)[:10]
    lines = [
        "# Quality Pack v3 Live Report",
        "",
        f"- Created: `{summary['created_at']}`",
        f"- Dataset: `{summary['dataset_version']}`",
        f"- Pipeline: `{summary.get('pipeline_version', '')}`",
        f"- Total: `{summary['total']}`",
        f"- Passed: `{summary['passed']}`",
        f"- Failed: `{summary['failed']}`",
        f"- Errors: `{summary['errors']}`",
        "",
        "## Data Sources",
    ]
    for meta in summary["feed_sources"]:
        lines.append(
            f"- `{meta['id']}`: {meta['name']} from {meta['source_url']} "
            f"status={meta['status']} items={meta['items_collected']}"
            + (f" error={meta['error']}" if meta.get("error") else "")
        )
    lines.extend(
        [
            "- Manual guardrails: BBC listing, Reuters homepage, Medium homepage, YouTube video.",
            "- Manual fact-check seed: PolitiFact explicit-ruling page.",
            "- Manual simple facts: arithmetic and common taste/property checks.",
            "",
            "## Summary",
            f"- By case type: `{json.dumps(summary['by_case_type'], ensure_ascii=False)}`",
            f"- By source type: `{json.dumps(summary['by_source_type'], ensure_ascii=False)}`",
            f"- By credibility label: `{json.dumps(summary['by_credibility_label'], ensure_ascii=False)}`",
            f"- By verdict: `{json.dumps(summary['by_verdict'], ensure_ascii=False)}`",
            "",
            "## Failed / Needs Review",
        ]
    )
    if not failed:
        lines.append("- None.")
    for row in failed[:30]:
        lines.append(
            f"- `{row['id']}` {row.get('case_type')} {row.get('source_domain', '')}: "
            f"label={row.get('credibility_label')} score={row.get('credibility_score')} "
            f"verdict={row.get('verdict')} issues={row.get('issues')} url={row.get('url')}"
        )
    lines.extend(["", "## Slowest Cases"])
    for row in slow:
        lines.append(
            f"- `{row['id']}` runtime={row.get('runtime_sec')}s "
            f"label={row.get('credibility_label')} verdict={row.get('verdict')} url={row.get('url')}"
        )
    lines.extend(["", "## Full Rows", "See JSON output for evidence, queries, timings and risk flags."])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and run Quality Pack v3 live URL checks.")
    parser.add_argument("--per-source", type=int, default=2, help="RSS article URLs collected per publisher")
    parser.add_argument("--max-cases", type=int, default=32, help="Maximum total cases including manual guardrails")
    parser.add_argument("--json-out", default="reports/quality_pack_v3_live.json")
    parser.add_argument("--md-out", default="reports/quality_pack_v3_live.md")
    args = parser.parse_args()

    cases, feed_meta = collect_cases(per_source=max(1, args.per_source), max_cases=max(1, args.max_cases))
    rows = [_run_case(case) for case in cases]
    summary = _summarize(rows, feed_meta)
    output = {"summary": summary, "rows": rows}

    json_path = ROOT / args.json_out
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    md_path = ROOT / args.md_out
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_markdown_report(summary, rows), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
