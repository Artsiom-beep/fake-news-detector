from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .schemas import ConfigSnapshot

PIPELINE_VERSION = "best_accuracy_v2"

MODEL_VERSIONS: Dict[str, str] = {
    "stance_model": "disabled_in_best_accuracy",
    "retrieval_ranker": "deterministic_lexical_v1",
    "summary_policy": "template_v1",
    "claim_prior": "disabled_in_best_accuracy",
    "common_knowledge": "local_rules_v2+wikipedia_summary_v2+categories+safe_abstention_v1",
    "news_credibility": "source_quality_corroboration_v1",
    "screenshot_ocr": "rapidocr_onnxruntime_v1",
    "ai_image_detection": "metadata_forensics_v1_optional_model",
}

_ENV_FILE_LOADED = False


def load_env_file(path: str | Path | None = None) -> None:
    """Load simple KEY=VALUE pairs from .env without adding a runtime dependency."""
    global _ENV_FILE_LOADED
    if _ENV_FILE_LOADED:
        return
    _ENV_FILE_LOADED = True
    env_path = Path(path) if path is not None else Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, value.strip().strip("\"'"))


load_env_file()

FACTCHECK_ONLY_DOMAINS: List[str] = [
    "factcheck.org",
    "snopes.com",
    "politifact.com",
    "leadstories.com",
    "fullfact.org",
    "checkyourfact.com",
    "africacheck.org",
    "factcheck.afp.com",
    "boomlive.in",
    "newschecker.in",
    "altnews.in",
]

RESEARCH_DOMAINS: List[str] = [
    "reuters.com",
    "apnews.com",
    "afp.com",
    "bbc.com",
    "bbc.co.uk",
    "npr.org",
    "theguardian.com",
    "aljazeera.com",
    "dw.com",
    "france24.com",
    "cbsnews.com",
    "nbcnews.com",
    "abcnews.go.com",
    "news.sky.com",
    *FACTCHECK_ONLY_DOMAINS,
]

HARD_TRUSTED_TYPES = {"institutional", "primary_news", "factcheck_org"}


@dataclass(frozen=True)
class PipelineConfig:
    pipeline_version: str = PIPELINE_VERSION
    mode: str = "best_accuracy"
    fast_mode: bool = False
    max_claims: int = 4
    max_search_results: int = 8
    max_documents: int = 8
    max_evidence: int = 6
    hard_min_independent: int = 2
    hard_min_trusted: int = 1
    decision_margin: float = 0.16
    min_dominant_score: float = 0.62
    prior_probability_threshold: float = 0.55
    prior_margin_threshold: float = 0.10
    allow_prior_fallback: bool = True
    targeted_domains: List[str] = field(default_factory=lambda: list(RESEARCH_DOMAINS))
    model_versions: Dict[str, str] = field(default_factory=lambda: dict(MODEL_VERSIONS))

    def snapshot(self) -> ConfigSnapshot:
        return ConfigSnapshot(
            pipeline_version=self.pipeline_version,
            mode=self.mode,
            fast_mode=self.fast_mode,
            max_claims=self.max_claims,
            max_documents=self.max_documents,
            max_evidence=self.max_evidence,
            hard_min_independent=self.hard_min_independent,
            hard_min_trusted=self.hard_min_trusted,
            decision_margin=self.decision_margin,
            prior_probability_threshold=self.prior_probability_threshold,
            prior_margin_threshold=self.prior_margin_threshold,
            model_versions=dict(self.model_versions),
        )


def build_config(fast_mode: bool | None = None, mode: str | None = None) -> PipelineConfig:
    """Build the single public product config.

    ``fast_mode`` and ``mode`` are accepted only for backward-compatible callers.
    Public entrypoints no longer expose them; the orchestrator chooses internal
    strategies while preserving a stable external config snapshot.
    """
    max_search_results = int(os.getenv("FACTCHECK_MAX_SEARCH_RESULTS", "8"))
    max_documents = int(os.getenv("FACTCHECK_MAX_DOCUMENTS", "8"))
    max_evidence = int(os.getenv("FACTCHECK_MAX_EVIDENCE", "6"))
    return PipelineConfig(
        mode="best_accuracy",
        fast_mode=False,
        max_claims=int(os.getenv("FACTCHECK_MAX_CLAIMS", "4")),
        max_search_results=max_search_results,
        max_documents=max_documents,
        max_evidence=max_evidence,
        hard_min_independent=int(os.getenv("FACTCHECK_HARD_MIN_INDEPENDENT", "2")),
        hard_min_trusted=int(os.getenv("FACTCHECK_HARD_MIN_TRUSTED", "1")),
        decision_margin=float(os.getenv("FACTCHECK_DECISION_MARGIN", "0.16")),
        min_dominant_score=float(os.getenv("FACTCHECK_MIN_DOMINANT_SCORE", "0.62")),
        prior_probability_threshold=float(os.getenv("FACTCHECK_PRIOR_PROBABILITY_THRESHOLD", "0.55")),
        prior_margin_threshold=float(os.getenv("FACTCHECK_PRIOR_MARGIN_THRESHOLD", "0.10")),
        allow_prior_fallback=os.getenv("FACTCHECK_ALLOW_PRIOR_FALLBACK", "1") not in {"0", "false", "False"},
        targeted_domains=list(RESEARCH_DOMAINS),
        model_versions=dict(MODEL_VERSIONS),
    )
