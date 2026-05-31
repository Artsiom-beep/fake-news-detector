import argparse
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
import sys
from typing import Dict, Iterable, List

import torch
import torch.nn.functional as F
from torch import nn
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src"))

from factcheck.claim_prior import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_MODEL_PATH,
    ID_TO_LABEL,
    LABEL_TO_ID,
    ClaimPriorNet,
    featurize_text,
)


def load_jsonl(path: Path) -> List[Dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def seed_everything(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)


class JsonlClaimDataset(Dataset):
    def __init__(self, rows: List[Dict], num_buckets: int):
        self.rows = rows
        self.num_buckets = int(num_buckets)

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> Dict:
        row = self.rows[index]
        text = str(row.get("text", ""))
        label = LABEL_TO_ID[str(row.get("expected", "uncertain"))]
        features = featurize_text(text, self.num_buckets)
        return {
            "id": str(row.get("id", index)),
            "text": text,
            "label": label,
            "feature_ids": features,
        }


def collate_batch(batch: List[Dict]) -> Dict[str, torch.Tensor | List[str]]:
    flat_ids: List[int] = []
    offsets: List[int] = []
    labels: List[int] = []
    texts: List[str] = []
    row_ids: List[str] = []
    offset = 0
    for item in batch:
        features = item["feature_ids"] or [0]
        offsets.append(offset)
        flat_ids.extend(features)
        offset += len(features)
        labels.append(int(item["label"]))
        texts.append(str(item["text"]))
        row_ids.append(str(item["id"]))
    return {
        "feature_ids": torch.tensor(flat_ids, dtype=torch.long),
        "offsets": torch.tensor(offsets, dtype=torch.long),
        "labels": torch.tensor(labels, dtype=torch.long),
        "texts": texts,
        "ids": row_ids,
    }


def class_weights(rows: Iterable[Dict]) -> torch.Tensor:
    counts = Counter(str(row.get("expected", "uncertain")) for row in rows)
    total = sum(counts.values())
    weights = []
    for label in ("true", "fake", "uncertain"):
        count = max(counts.get(label, 0), 1)
        weights.append(total / (3.0 * count))
    return torch.tensor(weights, dtype=torch.float32)


def compute_metrics(logits: torch.Tensor, labels: torch.Tensor) -> Dict:
    preds = torch.argmax(logits, dim=-1)
    num_classes = logits.shape[-1]
    confusion = [[0 for _ in range(num_classes)] for _ in range(num_classes)]
    for truth, pred in zip(labels.tolist(), preds.tolist()):
        confusion[truth][pred] += 1

    total = max(int(labels.numel()), 1)
    correct = int((preds == labels).sum().item())
    per_class = {}
    f1_values = []
    for class_id in range(num_classes):
        tp = confusion[class_id][class_id]
        fp = sum(confusion[row][class_id] for row in range(num_classes) if row != class_id)
        fn = sum(confusion[class_id][col] for col in range(num_classes) if col != class_id)
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 0.0 if precision + recall == 0 else (2 * precision * recall) / (precision + recall)
        per_class[ID_TO_LABEL[class_id]] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": sum(confusion[class_id]),
        }
        f1_values.append(f1)

    return {
        "accuracy": correct / total,
        "macro_f1": sum(f1_values) / max(len(f1_values), 1),
        "confusion_matrix": confusion,
        "per_class": per_class,
    }


@torch.no_grad()
def evaluate_model(model: ClaimPriorNet, loader: DataLoader, device: torch.device) -> Dict:
    model.eval()
    losses = []
    logits_all = []
    labels_all = []
    ids_all = []
    texts_all = []
    for batch in loader:
        feature_ids = batch["feature_ids"].to(device)
        offsets = batch["offsets"].to(device)
        labels = batch["labels"].to(device)
        logits = model(feature_ids, offsets)
        loss = F.cross_entropy(logits, labels)
        losses.append(float(loss.item()))
        logits_all.append(logits.cpu())
        labels_all.append(labels.cpu())
        ids_all.extend(batch["ids"])
        texts_all.extend(batch["texts"])

    if not logits_all:
        return {
            "loss": 0.0,
            "accuracy": 0.0,
            "macro_f1": 0.0,
            "confusion_matrix": [[0, 0, 0], [0, 0, 0], [0, 0, 0]],
            "per_class": {},
            "details": [],
        }

    logits = torch.cat(logits_all, dim=0)
    labels = torch.cat(labels_all, dim=0)
    metrics = compute_metrics(logits, labels)
    probs = torch.softmax(logits, dim=-1)
    details = []
    for row_id, text, prob_row, label in zip(ids_all, texts_all, probs.tolist(), labels.tolist()):
        pred = int(max(range(len(prob_row)), key=lambda index: prob_row[index]))
        ranked = sorted(prob_row, reverse=True)
        details.append(
            {
                "id": row_id,
                "text": text,
                "expected": ID_TO_LABEL[int(label)],
                "pred": ID_TO_LABEL[pred],
                "top_probability": float(prob_row[pred]),
                "margin": float(ranked[0] - (ranked[1] if len(ranked) > 1 else 0.0)),
                "probabilities": {
                    ID_TO_LABEL[index]: float(prob_row[index])
                    for index in range(len(prob_row))
                },
            }
        )

    metrics["loss"] = sum(losses) / max(len(losses), 1)
    metrics["details"] = details
    return metrics


def choose_safe_override(valid_metrics: Dict, min_precision: float = 0.8) -> Dict[str, float]:
    details = valid_metrics.get("details", [])
    best = {"probability": 0.95, "margin": 0.2, "precision": 0.0, "coverage": 0.0, "selected": 0}
    for prob_threshold in [round(0.50 + 0.05 * step, 2) for step in range(10)]:
        for margin_threshold in [round(0.05 * step, 2) for step in range(10)]:
            selected = []
            correct = 0
            for item in details:
                if item["pred"] not in {"true", "fake"}:
                    continue
                if item["top_probability"] < prob_threshold or item["margin"] < margin_threshold:
                    continue
                selected.append(item)
                correct += int(item["pred"] == item["expected"])
            if not selected:
                continue
            precision = correct / len(selected)
            coverage = len(selected) / max(len(details), 1)
            if precision < min_precision:
                continue
            if coverage > best["coverage"] or (math.isclose(coverage, best["coverage"]) and precision > best["precision"]):
                best = {
                    "probability": prob_threshold,
                    "margin": margin_threshold,
                    "precision": round(precision, 4),
                    "coverage": round(coverage, 4),
                    "selected": len(selected),
                }
    return best


def load_seed_rows(seed_path: Path, repeat: int = 0) -> List[Dict]:
    if not seed_path.exists() or repeat <= 0:
        return []
    rows = []
    for line in seed_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        stance = str(item.get("stance", "")).strip().lower()
        if stance == "support":
            label = "true"
        elif stance == "refute":
            label = "fake"
        else:
            continue
        claim_text = str(item.get("claim", "")).strip()
        if not claim_text:
            continue
        rows.append({"id": f"seed::{item.get('topic', 'row')}", "text": claim_text, "expected": label})
    return rows * max(int(repeat), 1)


def run_epoch(model: ClaimPriorNet, loader: DataLoader, optimizer, device: torch.device, ce_weights: torch.Tensor) -> float:
    model.train()
    losses = []
    ce_weights = ce_weights.to(device)
    for batch in loader:
        feature_ids = batch["feature_ids"].to(device)
        offsets = batch["offsets"].to(device)
        labels = batch["labels"].to(device)

        optimizer.zero_grad()
        logits = model(feature_ids, offsets)
        loss = F.cross_entropy(logits, labels, weight=ce_weights, label_smoothing=0.03)
        if torch.isnan(loss) or torch.isinf(loss):
            continue
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()
        losses.append(float(loss.item()))
    return sum(losses) / max(len(losses), 1)


def main(
    dataset_path: str,
    out_dir: str,
    seed_path: str,
    seed_repeat: int,
    num_buckets: int,
    embedding_dim: int,
    hidden_dim: int,
    dropout: float,
    batch_size: int,
    epochs: int,
    lr: float,
    weight_decay: float,
    patience: int,
    seed: int,
) -> None:
    seed_everything(seed)
    rows = load_jsonl(Path(dataset_path))
    train_rows = [row for row in rows if row.get("split") == "train"]
    valid_rows = [row for row in rows if row.get("split") == "valid"]
    test_rows = [row for row in rows if row.get("split") == "test"]
    train_rows = train_rows + load_seed_rows(Path(seed_path), repeat=seed_repeat)

    train_ds = JsonlClaimDataset(train_rows, num_buckets=num_buckets)
    valid_ds = JsonlClaimDataset(valid_rows, num_buckets=num_buckets)
    test_ds = JsonlClaimDataset(test_rows, num_buckets=num_buckets)

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, collate_fn=collate_batch)
    valid_loader = DataLoader(valid_ds, batch_size=batch_size, shuffle=False, collate_fn=collate_batch)
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False, collate_fn=collate_batch)

    device = torch.device("cpu")
    model = ClaimPriorNet(
        num_buckets=num_buckets,
        embedding_dim=embedding_dim,
        hidden_dim=hidden_dim,
        dropout=dropout,
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    ce_weights = class_weights(train_rows)

    best_valid_f1 = -1.0
    best_state = None
    best_valid_metrics = None
    history = []
    patience_left = int(patience)

    for epoch in range(1, epochs + 1):
        train_loss = run_epoch(model, train_loader, optimizer, device, ce_weights)
        valid_metrics = evaluate_model(model, valid_loader, device)
        history.append(
            {
                "epoch": epoch,
                "train_loss": train_loss,
                "valid_loss": valid_metrics["loss"],
                "valid_accuracy": valid_metrics["accuracy"],
                "valid_macro_f1": valid_metrics["macro_f1"],
            }
        )
        print(
            json.dumps(
                {
                    "epoch": epoch,
                    "train_loss": round(train_loss, 4),
                    "valid_accuracy": round(valid_metrics["accuracy"], 4),
                    "valid_macro_f1": round(valid_metrics["macro_f1"], 4),
                },
                ensure_ascii=False,
            )
        )

        if valid_metrics["macro_f1"] > best_valid_f1:
            best_valid_f1 = valid_metrics["macro_f1"]
            best_state = {key: value.cpu().clone() for key, value in model.state_dict().items()}
            best_valid_metrics = valid_metrics
            patience_left = int(patience)
        else:
            patience_left -= 1
            if patience_left <= 0:
                print(json.dumps({"early_stop": True, "epoch": epoch}, ensure_ascii=False))
                break

    if best_state is None:
        best_state = model.state_dict()
        best_valid_metrics = evaluate_model(model, valid_loader, device)

    model.load_state_dict(best_state)
    test_metrics = evaluate_model(model, test_loader, device)
    safe_override = choose_safe_override(best_valid_metrics, min_precision=0.8)

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    model_path = out_path / DEFAULT_MODEL_PATH.name
    config_path = out_path / DEFAULT_CONFIG_PATH.name
    metrics_path = out_path / "metrics.json"

    torch.save(model.state_dict(), model_path)
    config_path.write_text(
        json.dumps(
            {
                "label_to_id": LABEL_TO_ID,
                "id_to_label": {str(key): value for key, value in ID_TO_LABEL.items()},
                "num_buckets": num_buckets,
                "embedding_dim": embedding_dim,
                "hidden_dim": hidden_dim,
                "dropout": dropout,
                "safe_override": safe_override,
                "dataset_path": dataset_path,
                "seed_path": seed_path,
                "seed_repeat": seed_repeat,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    metrics_path.write_text(
        json.dumps(
            {
                "history": history,
                "best_valid": {
                    key: value
                    for key, value in best_valid_metrics.items()
                    if key != "details"
                },
                "test": {
                    key: value
                    for key, value in test_metrics.items()
                    if key != "details"
                },
                "safe_override": safe_override,
                "train_size": len(train_rows),
                "valid_size": len(valid_rows),
                "test_size": len(test_rows),
                "class_weights": ce_weights.tolist(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "model_path": str(model_path),
                "config_path": str(config_path),
                "metrics_path": str(metrics_path),
                "best_valid_accuracy": round(best_valid_metrics["accuracy"], 4),
                "best_valid_macro_f1": round(best_valid_metrics["macro_f1"], 4),
                "test_accuracy": round(test_metrics["accuracy"], 4),
                "test_macro_f1": round(test_metrics["macro_f1"], 4),
                "safe_override": safe_override,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train a lightweight 3-class claim-prior model for fact-check fallback")
    parser.add_argument("--dataset", default="data/factcheck/external/liar_official_v1_all.jsonl")
    parser.add_argument("--out-dir", default="outputs/factcheck_models/claim_prior_v1")
    parser.add_argument("--seed-path", default="data/factcheck/seed_evidence.jsonl")
    parser.add_argument("--seed-repeat", type=int, default=40)
    parser.add_argument("--num-buckets", type=int, default=200000)
    parser.add_argument("--embedding-dim", type=int, default=96)
    parser.add_argument("--hidden-dim", type=int, default=192)
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--lr", type=float, default=0.002)
    parser.add_argument("--weight-decay", type=float, default=0.0001)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    main(
        dataset_path=args.dataset,
        out_dir=args.out_dir,
        seed_path=args.seed_path,
        seed_repeat=args.seed_repeat,
        num_buckets=args.num_buckets,
        embedding_dim=args.embedding_dim,
        hidden_dim=args.hidden_dim,
        dropout=args.dropout,
        batch_size=args.batch_size,
        epochs=args.epochs,
        lr=args.lr,
        weight_decay=args.weight_decay,
        patience=args.patience,
        seed=args.seed,
    )
