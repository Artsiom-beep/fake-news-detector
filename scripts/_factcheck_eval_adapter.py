from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from factcheck.ingest import fetch_url_text as _fetch_url_payload
from factcheck.service import run_factcheck as _run_factcheck
from nli import set_fast_mode


def fetch_article_text(url: str, timeout: int = 15) -> str:
    payload = _fetch_url_payload(url, timeout=timeout)
    if isinstance(payload, dict):
        return (
            payload.get("text")
            or payload.get("claim_text")
            or payload.get("ruling_text")
            or payload.get("title")
            or ""
        )
    return str(payload or "")


def run_factcheck_public(text: str) -> dict[str, Any]:
    return _run_factcheck(text=text).to_public_dict()


def run_factcheck_eval_view(text: str) -> dict[str, Any]:
    public = run_factcheck_public(text)
    claims = public.get("claims", [])
    evidence = public.get("evidence", [])
    claim_verdict_counts = Counter(
        claim.get("verdict", "uncertain")
        for claim in claims
        if isinstance(claim, dict)
    )
    evidence_types = Counter(
        item.get("source_type", "unknown")
        for item in evidence
        if isinstance(item, dict)
    )
    return {
        "article_verdict": public.get("verdict", "uncertain"),
        "confidence": public.get("confidence", 0.0),
        "summary": public.get("summary", ""),
        "claim": public.get("claim", ""),
        "evidence": evidence,
        "trace": public.get("trace", {}),
        "pipeline_version": public.get("pipeline_version", ""),
        "claims": claims,
        "claims_summary": {
            "supported": claim_verdict_counts.get("true", 0),
            "refuted": claim_verdict_counts.get("fake", 0),
            "insufficient": claim_verdict_counts.get("uncertain", 0),
        },
        "evidence_summary": {
            "total": len(evidence) if isinstance(evidence, list) else 0,
            "trusted": sum(
                1
                for item in evidence
                if isinstance(item, dict)
                and float(item.get("source_trust", 0.0) or 0.0) >= 0.9
            ),
            "by_source_type": dict(evidence_types),
        },
    }
