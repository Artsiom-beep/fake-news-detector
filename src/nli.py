from typing import Dict

_nli = None
_model_load_failed = False
_USE_LEXICAL_ONLY = False


def _load_pipeline():
    global _nli, _model_load_failed
    if _nli is not None or _model_load_failed:
        return _nli
    try:
        from transformers import pipeline
        model_name = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"
        _nli = pipeline("text-classification", model=model_name, tokenizer=model_name)
    except Exception:
        _model_load_failed = True
        _nli = None
    return _nli


def _lexical_fallback(claim: str, evidence: str) -> Dict:
    claim_txt = (claim or "").lower()
    ev_txt = (evidence or "").lower()
    c = set(__import__("re").findall(r"\w+", claim_txt))
    e = set(__import__("re").findall(r"\w+", ev_txt))
    if not c or not e:
        return {"label": "neutral", "score": 0.0}

    overlap = len(c & e) / max(len(c), 1)

    neg_markers = {
        "not", "no", "never", "false", "falsely", "fake", "misleading", "misrepresented",
        "denied", "deny", "hoax", "untrue", "incorrect", "wrong"
    }
    explicit_refute_phrases = [
        "not true",
        "false claim",
        "claim is false",
        "statement is false",
        "is false",
        "are false",
        "as false",
        "unsupported",
        "no evidence",
        "no credible evidence",
        "did not report",
        "did not announce",
        "did not confirm",
        "contradicts the claim",
        "contradicting claims",
        "contradicts claims",
    ]
    negative_quantity_markers = {
        "zero", "no", "none", "never", "without", "lack", "lacks", "lacking"
    }
    positive_growth_markers = {
        "strong", "higher", "high", "increase", "increased", "increasing", "grew",
        "growth", "growing", "surge", "surged", "record", "recorded", "robust", "rose"
    }
    claim_has_neg = len(c & neg_markers) > 0 or any(p in claim_txt for p in explicit_refute_phrases)
    ev_has_neg = len(e & neg_markers) > 0 or any(p in ev_txt for p in explicit_refute_phrases)
    claim_has_negative_quantity = len(c & negative_quantity_markers) > 0
    ev_has_negative_quantity = len(e & negative_quantity_markers) > 0
    claim_has_positive_growth = len(c & positive_growth_markers) > 0
    ev_has_positive_growth = len(e & positive_growth_markers) > 0

    # crude contradiction signal for fast mode:
    # high lexical overlap + opposite polarity in negation cues
    if overlap >= 0.35 and (claim_has_neg ^ ev_has_neg):
        return {"label": "refuted", "score": min(0.75, 0.45 + overlap * 0.4)}

    if overlap >= 0.20 and (
        (claim_has_negative_quantity and ev_has_positive_growth)
        or (claim_has_positive_growth and ev_has_negative_quantity)
    ):
        return {"label": "refuted", "score": min(0.82, 0.48 + overlap * 0.45)}

    # explicit debunk phrases in evidence should win before generic support overlap
    if overlap >= 0.20 and any(p in ev_txt for p in explicit_refute_phrases + ["falsely", "misleading", "contradict"]):
        return {"label": "refuted", "score": min(0.78, 0.46 + overlap * 0.3)}

    if overlap > 0.40:
        return {"label": "supported", "score": min(0.8, max(0.45, overlap))}

    return {"label": "neutral", "score": max(0.2, overlap)}


def set_fast_mode(enabled: bool = True):
    global _USE_LEXICAL_ONLY
    _USE_LEXICAL_ONLY = enabled


def classify_claim_vs_evidence(claim: str, evidence_text: str) -> Dict:
    if not evidence_text:
        return {"label": "neutral", "score": 0.0}

    if _USE_LEXICAL_ONLY:
        return _lexical_fallback(claim, evidence_text)

    nli = _load_pipeline()
    if nli is None:
        return _lexical_fallback(claim, evidence_text)

    try:
        text = f"premise: {evidence_text[:1200]} hypothesis: {claim}"
        out = nli(text, truncation=True, max_length=512)[0]
        label = out.get("label", "").lower()
        if "entail" in label:
            norm = "supported"
        elif "contrad" in label:
            norm = "refuted"
        else:
            norm = "neutral"
        return {"label": norm, "score": float(out.get("score", 0.0))}
    except Exception:
        return _lexical_fallback(claim, evidence_text)
