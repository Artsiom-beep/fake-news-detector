from __future__ import annotations

from typing import Dict

try:
    from .fact_pipeline import run_factcheck as run_factcheck_legacy
except ImportError:
    from fact_pipeline import run_factcheck as run_factcheck_legacy


def run_factcheck_v3(article_text: str) -> Dict:
    return run_factcheck_legacy(article_text)
