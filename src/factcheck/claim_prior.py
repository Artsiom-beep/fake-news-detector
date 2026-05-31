from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Dict, Iterable, List

LABEL_TO_ID = {"true": 0, "fake": 1, "uncertain": 2}
ID_TO_LABEL = {value: key for key, value in LABEL_TO_ID.items()}

DEFAULT_MODEL_DIR = Path("outputs/factcheck_models/claim_prior_v1")
DEFAULT_MODEL_PATH = DEFAULT_MODEL_DIR / "model.pt"
DEFAULT_CONFIG_PATH = DEFAULT_MODEL_DIR / "config.json"

TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:'[a-z0-9]+)?", flags=re.I)
UNCERTAINTY_PATTERN = re.compile(
    r"\b(?:"
    r"anonymous|unverified|rumou?r|no\s+(?:official\s+|reliable\s+|credible\s+|verifiable\s+)?evidence|"
    r"no\s+sources?|no\s+reliable\s+source|no\s+verifiable\s+source|cannot\s+be\s+verified|can't\s+be\s+verified|"
    r"mixed\s+evidence|fast-moving\s+rumors|forum\s+says|social\s+media|blog\s+claims|channel\s+says"
    r")\b",
    flags=re.I,
)

_MODEL = None
_CONFIG = None
_TORCH: Any | None = None
_NN: Any | None = None
_CLAIM_PRIOR_NET_CLASS: type | None = None


def _torch_available() -> bool:
    return find_spec("torch") is not None


def _load_torch() -> tuple[Any, Any] | tuple[None, None]:
    global _TORCH, _NN
    if _TORCH is not None and _NN is not None:
        return _TORCH, _NN
    if not _torch_available():
        return None, None
    try:
        _TORCH = import_module("torch")
        _NN = import_module("torch.nn")
    except Exception:  # pragma: no cover - optional research dependency
        _TORCH = None
        _NN = None
    return _TORCH, _NN


def normalize_text(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def tokenize_text(text: str) -> List[str]:
    return TOKEN_PATTERN.findall(normalize_text(text))


def build_feature_strings(text: str) -> List[str]:
    tokens = tokenize_text(text)
    if not tokens:
        return ["__empty__"]

    features: List[str] = []
    for token in tokens:
        features.append(f"w:{token}")

    for index in range(len(tokens) - 1):
        features.append(f"b:{tokens[index]}_{tokens[index + 1]}")

    compact = re.sub(r"[^a-z0-9]+", " ", normalize_text(text)).strip()
    if compact:
        padded = f"^{compact}$"
        for size in (3, 4, 5):
            if len(padded) < size:
                continue
            for start in range(0, len(padded) - size + 1):
                gram = padded[start : start + size]
                if " " in gram and gram.strip() == "":
                    continue
                features.append(f"c{size}:{gram}")

    return features or ["__empty__"]


def hash_feature(feature: str, num_buckets: int) -> int:
    return zlib.crc32(feature.encode("utf-8")) % max(int(num_buckets), 1)


def featurize_text(text: str, num_buckets: int) -> List[int]:
    feature_ids = [hash_feature(feature, num_buckets) for feature in build_feature_strings(text)]
    return feature_ids or [0]


def _get_claim_prior_net_class() -> type:
    global _CLAIM_PRIOR_NET_CLASS
    if _CLAIM_PRIOR_NET_CLASS is not None:
        return _CLAIM_PRIOR_NET_CLASS

    _torch, nn = _load_torch()
    if nn is None:
        raise RuntimeError("claim_prior requires optional torch dependency")

    class _ClaimPriorNet(nn.Module):
        def __init__(self, num_buckets: int, embedding_dim: int, hidden_dim: int, num_classes: int = 3, dropout: float = 0.2):
            super().__init__()
            self.num_buckets = int(num_buckets)
            self.embedding_dim = int(embedding_dim)
            self.hidden_dim = int(hidden_dim)
            self.num_classes = int(num_classes)
            self.embedding = nn.EmbeddingBag(self.num_buckets, self.embedding_dim, mode="mean")
            self.dropout = nn.Dropout(float(dropout))
            self.classifier = nn.Sequential(
                nn.Linear(self.embedding_dim, self.hidden_dim),
                nn.ReLU(),
                nn.Dropout(float(dropout)),
                nn.Linear(self.hidden_dim, self.num_classes),
            )
            self._reset_parameters()

        def _reset_parameters(self) -> None:
            nn.init.normal_(self.embedding.weight, mean=0.0, std=0.02)
            for module in self.classifier:
                if isinstance(module, nn.Linear):
                    nn.init.xavier_uniform_(module.weight)
                    nn.init.zeros_(module.bias)

        def forward(self, feature_ids, offsets):
            pooled = self.embedding(feature_ids, offsets)
            pooled = self.dropout(pooled)
            return self.classifier(pooled)

    _CLAIM_PRIOR_NET_CLASS = _ClaimPriorNet
    return _CLAIM_PRIOR_NET_CLASS


class ClaimPriorNet:
    """Compatibility factory for the optional Torch-backed claim prior model."""

    def __new__(cls, *args, **kwargs):
        return _get_claim_prior_net_class()(*args, **kwargs)


@dataclass(frozen=True)
class ClaimPriorPrediction:
    label: str
    confidence: float
    margin: float
    probabilities: Dict[str, float]


def has_uncertainty_markers(text: str) -> bool:
    return bool(UNCERTAINTY_PATTERN.search(text or ""))


def _load_config(config_path: Path | str = DEFAULT_CONFIG_PATH) -> Dict | None:
    path = Path(config_path)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def claim_prior_available(model_path: Path | str = DEFAULT_MODEL_PATH, config_path: Path | str = DEFAULT_CONFIG_PATH) -> bool:
    return _torch_available() and Path(model_path).exists() and Path(config_path).exists()


def load_claim_prior(model_path: Path | str = DEFAULT_MODEL_PATH, config_path: Path | str = DEFAULT_CONFIG_PATH):
    global _MODEL, _CONFIG
    model_path = Path(model_path)
    config_path = Path(config_path)
    if _MODEL is not None and _CONFIG is not None:
        return _MODEL, _CONFIG
    if not claim_prior_available(model_path=model_path, config_path=config_path):
        return None, None

    config = _load_config(config_path)
    torch, _nn = _load_torch()
    if torch is None:
        return None, None
    model = ClaimPriorNet(
        num_buckets=int(config["num_buckets"]),
        embedding_dim=int(config["embedding_dim"]),
        hidden_dim=int(config["hidden_dim"]),
        num_classes=len(config.get("label_to_id", LABEL_TO_ID)),
        dropout=float(config.get("dropout", 0.2)),
    )
    state = torch.load(model_path, map_location="cpu")
    model.load_state_dict(state)
    model.eval()
    _MODEL, _CONFIG = model, config
    return _MODEL, _CONFIG


def predict_claim_prior(
    text: str,
    model_path: Path | str = DEFAULT_MODEL_PATH,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> ClaimPriorPrediction | None:
    model, config = load_claim_prior(model_path=model_path, config_path=config_path)
    if model is None or config is None:
        return None

    torch, _nn = _load_torch()
    if torch is None:
        return None

    feature_ids = featurize_text(text, int(config["num_buckets"]))
    ids_tensor = torch.tensor(feature_ids, dtype=torch.long)
    offsets_tensor = torch.tensor([0], dtype=torch.long)

    with torch.no_grad():
        logits = model(ids_tensor, offsets_tensor)
        probs_tensor = torch.softmax(logits, dim=-1)[0]

    probabilities = {
        ID_TO_LABEL[index]: float(probs_tensor[index].item())
        for index in range(len(probs_tensor))
    }
    ranked = sorted(probabilities.items(), key=lambda item: item[1], reverse=True)
    label, confidence = ranked[0]
    margin = confidence - (ranked[1][1] if len(ranked) > 1 else 0.0)
    return ClaimPriorPrediction(
        label=label,
        confidence=float(confidence),
        margin=float(margin),
        probabilities=probabilities,
    )


def get_safe_prior_thresholds(config_path: Path | str = DEFAULT_CONFIG_PATH) -> Dict[str, float]:
    config = _load_config(config_path)
    if not config:
        return {"probability": 0.9, "margin": 0.2}
    safe = config.get("safe_override", {})
    return {
        "probability": float(safe.get("probability", 0.9)),
        "margin": float(safe.get("margin", 0.2)),
    }


def select_safe_prior_prediction(
    text: str,
    probability_threshold: float = 0.55,
    margin_threshold: float = 0.10,
    allow_uncertain_markers: bool = False,
    model_path: Path | str = DEFAULT_MODEL_PATH,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
) -> ClaimPriorPrediction | None:
    if not allow_uncertain_markers and has_uncertainty_markers(text):
        return None

    prediction = predict_claim_prior(text, model_path=model_path, config_path=config_path)
    if prediction is None:
        return None
    if prediction.label not in {"true", "fake"}:
        return None
    if prediction.confidence < float(probability_threshold):
        return None
    if prediction.margin < float(margin_threshold):
        return None
    return prediction


def predict_many_texts(texts: Iterable[str], model_path: Path | str = DEFAULT_MODEL_PATH, config_path: Path | str = DEFAULT_CONFIG_PATH) -> List[ClaimPriorPrediction | None]:
    return [predict_claim_prior(text, model_path=model_path, config_path=config_path) for text in texts]
