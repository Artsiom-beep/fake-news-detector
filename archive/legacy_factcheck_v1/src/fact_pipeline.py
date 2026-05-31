from __future__ import annotations

from collections import Counter
from typing import Dict

try:
    from .factcheck.service import run_factcheck as run_factcheck_v1
except ImportError:
    from factcheck.service import run_factcheck as run_factcheck_v1


def _legacy_payload(public: Dict) -> Dict:
    claims = public.get("claims", [])
    evidence = public.get("evidence", [])
    claim_verdict_counts = Counter(claim.get("verdict", "uncertain") for claim in claims)
    evidence_types = Counter(item.get("source_type", "unknown") for item in evidence)

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
            "total": len(evidence),
            "trusted": sum(1 for item in evidence if float(item.get("source_trust", 0.0)) >= 0.9),
            "by_source_type": dict(evidence_types),
        },
    }


def run_factcheck(article_text: str) -> Dict:
    result = run_factcheck_v1(text=article_text, fast_mode=True)
    return _legacy_payload(result.to_public_dict())
