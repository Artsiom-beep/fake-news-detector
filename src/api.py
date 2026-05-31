from __future__ import annotations

from pydantic import BaseModel, ConfigDict

try:
    from .api_factcheck import app
    from .factcheck.service import run_factcheck
except ImportError:
    from api_factcheck import app
    from factcheck.service import run_factcheck


class LegacyPredictRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = ""
    transcript: str | None = ""


@app.post("/predict")
def predict_legacy(request: LegacyPredictRequest):
    """Compatibility endpoint for the old prototype API.

    The original endpoint loaded an untrained multimodal Torch model at import
    time. Keeping the route but delegating to the canonical fact-check engine
    avoids two competing product APIs.
    """
    text = " ".join(part.strip() for part in [request.text or "", request.transcript or ""] if part and part.strip())
    result = run_factcheck(text=text)
    payload = result.to_public_dict()
    legacy_label = {
        "true": "real",
        "fake": "fake",
        "uncertain": "uncertain",
    }.get(payload.get("verdict", "uncertain"), "uncertain")
    return {
        **payload,
        "label": legacy_label,
        "fake_probability": payload.get("confidence", 0.0) if legacy_label == "fake" else 0.0,
        "compatibility": "legacy_predict_delegates_to_factcheck",
    }
