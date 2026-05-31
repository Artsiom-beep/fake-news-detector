from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Dict

LABEL_TO_ID = {"true": 0, "fake": 1, "uncertain": 2}
ID_TO_LABEL = {value: key for key, value in LABEL_TO_ID.items()}

DEFAULT_MODEL_DIR = Path("outputs/factcheck_models/claim_prior_transformer_v1")

_TOKENIZER = None
_MODEL = None
_CONFIG = None
_TORCH: Any | None = None
_AUTO_MODEL: Any | None = None
_AUTO_TOKENIZER: Any | None = None


def _optional_dependencies_available() -> bool:
    return find_spec("torch") is not None and find_spec("transformers") is not None


def _load_optional_dependencies() -> tuple[Any, Any, Any] | tuple[None, None, None]:
    global _TORCH, _AUTO_MODEL, _AUTO_TOKENIZER
    if _TORCH is not None and _AUTO_MODEL is not None and _AUTO_TOKENIZER is not None:
        return _TORCH, _AUTO_MODEL, _AUTO_TOKENIZER
    if not _optional_dependencies_available():
        return None, None, None
    try:
        _TORCH = import_module("torch")
        transformers = import_module("transformers")
        _AUTO_MODEL = transformers.AutoModelForSequenceClassification
        _AUTO_TOKENIZER = transformers.AutoTokenizer
    except Exception:  # pragma: no cover - optional research dependency
        _TORCH = None
        _AUTO_MODEL = None
        _AUTO_TOKENIZER = None
    return _TORCH, _AUTO_MODEL, _AUTO_TOKENIZER


@dataclass(frozen=True)
class ClaimPriorTransformerPrediction:
    label: str
    confidence: float
    margin: float
    probabilities: Dict[str, float]


def claim_prior_transformer_available(model_dir: Path | str = DEFAULT_MODEL_DIR) -> bool:
    path = Path(model_dir)
    has_model_files = (path / "config.json").exists() and (
        (path / "model.safetensors").exists() or (path / "pytorch_model.bin").exists()
    )
    return has_model_files and _optional_dependencies_available()


def load_claim_prior_transformer(model_dir: Path | str = DEFAULT_MODEL_DIR):
    global _TOKENIZER, _MODEL, _CONFIG
    path = Path(model_dir)
    if _TOKENIZER is not None and _MODEL is not None and _CONFIG is not None:
        return _TOKENIZER, _MODEL, _CONFIG
    if not claim_prior_transformer_available(path):
        return None, None, None
    _torch, auto_model, auto_tokenizer = _load_optional_dependencies()
    if auto_model is None or auto_tokenizer is None:
        return None, None, None
    tokenizer = auto_tokenizer.from_pretrained(path)
    model = auto_model.from_pretrained(path)
    config_path = path / "claim_prior_config.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    model.eval()
    _TOKENIZER, _MODEL, _CONFIG = tokenizer, model, config
    return _TOKENIZER, _MODEL, _CONFIG


def predict_claim_prior_transformer(text: str, model_dir: Path | str = DEFAULT_MODEL_DIR) -> ClaimPriorTransformerPrediction | None:
    tokenizer, model, _config = load_claim_prior_transformer(model_dir=model_dir)
    if tokenizer is None or model is None:
        return None

    torch, _auto_model, _auto_tokenizer = _load_optional_dependencies()
    if torch is None:
        return None

    encoded = tokenizer(
        text or "",
        truncation=True,
        max_length=96,
        padding=False,
        return_tensors="pt",
    )
    with torch.no_grad():
        logits = model(**encoded).logits
        probs = torch.softmax(logits, dim=-1)[0]
    probabilities = {ID_TO_LABEL[index]: float(probs[index].item()) for index in range(len(probs))}
    ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    label, confidence = ranked[0]
    margin = confidence - (ranked[1][1] if len(ranked) > 1 else 0.0)
    return ClaimPriorTransformerPrediction(
        label=label,
        confidence=float(confidence),
        margin=float(margin),
        probabilities=probabilities,
    )
