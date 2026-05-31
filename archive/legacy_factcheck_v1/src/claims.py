try:
    from .factcheck.claims import extract_claims as _extract_claim_candidates
except ImportError:
    from factcheck.claims import extract_claims as _extract_claim_candidates


def extract_claims(text: str, max_claims: int = 8):
    return [candidate.normalized_text for candidate in _extract_claim_candidates(text, max_claims=max_claims)]
