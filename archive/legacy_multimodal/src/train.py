import argparse
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, WeightedRandomSampler
from tqdm import tqdm

from dataset import MultimodalNewsDataset
from models import MultimodalFakeNewsModel
import json
import csv
from evaluate import evaluate
from utils import load_config, set_seed, ensure_dir
from callbacks import EarlyStopping


def run_epoch(model, loader, optimizer, criterion, device):
    model.train()
    total_loss = 0.0

    for batch in tqdm(loader, desc='train', leave=False):
        input_ids = batch['input_ids'].to(device)
        attention_mask = batch['attention_mask'].to(device)
        image = batch['image'].to(device)
        video_frames = batch['video_frames'].to(device)
        labels = batch['label'].to(device)

        optimizer.zero_grad()
        logits = model(input_ids, attention_mask, image, video_frames)
        loss = criterion(logits, labels)
        if torch.isnan(loss) or torch.isinf(loss):
            continue
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
        optimizer.step()

        total_loss += loss.item()

    return total_loss / max(len(loader), 1)


def main(config_path: str):
    cfg = load_config(config_path)
    set_seed(cfg.get('seed', 42))

    device = torch.device(cfg.get('device', 'cpu'))

    train_ds = MultimodalNewsDataset(
        cfg['paths']['train_csv'],
        tokenizer_name=cfg['model']['text_model_name'],
        max_text_len=cfg['model']['max_text_len'],
        image_size=cfg['model']['image_size'],
        video_frames=cfg['model']['video_frames'],
        max_samples=cfg['model'].get('train_max_samples'),
    )
    val_ds = MultimodalNewsDataset(
        cfg['paths']['val_csv'],
        tokenizer_name=cfg['model']['text_model_name'],
        max_text_len=cfg['model']['max_text_len'],
        image_size=cfg['model']['image_size'],
        video_frames=cfg['model']['video_frames'],
        max_samples=cfg['model'].get('val_max_samples'),
    )

    # Class-balanced sampling to reduce single-class collapse on imbalanced datasets
    labels = [int(train_ds.df.iloc[i]['label']) for i in range(len(train_ds))]
    class_counts = [max(labels.count(0), 1), max(labels.count(1), 1)]
    sample_weights = [1.0 / class_counts[label] for label in labels]
    sampler = WeightedRandomSampler(
        weights=torch.as_tensor(sample_weights, dtype=torch.double),
        num_samples=len(sample_weights),
        replacement=True,
    )

    train_loader = DataLoader(
        train_ds,
        batch_size=cfg['train']['batch_size'],
        sampler=sampler,
        num_workers=cfg['train']['num_workers'],
    )
    val_loader = DataLoader(val_ds, batch_size=cfg['train']['batch_size'], shuffle=False, num_workers=cfg['train']['num_workers'])

    model = MultimodalFakeNewsModel(
        text_model_name=cfg['model']['text_model_name'],
        fusion_hidden=cfg['model']['fusion_hidden'],
        dropout=cfg['model']['dropout'],
        text_only=cfg['model'].get('text_only', False),
    ).to(device)

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(cfg['train']['lr']),
        weight_decay=float(cfg['train']['weight_decay'])
    )
    # class weighting for imbalance
    pos = sum(labels)
    neg = max(len(labels) - pos, 1)
    pos_weight = torch.tensor([neg / max(pos, 1)], dtype=torch.float32).to(device)
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    best_score = -1.0
    ensure_dir(cfg['train']['save_path'])
    stopper = EarlyStopping(patience=int(cfg['train'].get('patience', 2)), mode='max')
    history = []

    for epoch in range(cfg['train']['epochs']):
        train_loss = run_epoch(model, train_loader, optimizer, criterion, device)
        val_metrics = evaluate(model, val_loader, device, verbose=False, tune_threshold=True)
        print(f"Epoch {epoch+1}/{cfg['train']['epochs']} | loss={train_loss:.4f} | val={val_metrics}")

        history.append({'epoch': epoch + 1, 'loss': train_loss, **val_metrics})

        current_score = val_metrics.get('macro_f1', val_metrics['f1'])
        if current_score > best_score:
            best_score = current_score
            torch.save(model.state_dict(), cfg['train']['save_path'])
            print(f"Saved best model to {cfg['train']['save_path']} (macro_f1={best_score:.4f}, thr={val_metrics['threshold']:.2f})")

        if stopper.step(current_score):
            print('Early stopping triggered.')
            break

    # save final metrics artifacts
    metrics_path = cfg['train'].get('metrics_json', 'outputs/metrics.json')
    confusion_path = cfg['train'].get('confusion_csv', 'outputs/confusion_matrix.csv')
    ensure_dir(metrics_path)
    ensure_dir(confusion_path)

    final = history[-1] if history else {}
    with open(metrics_path, 'w', encoding='utf-8') as f:
        json.dump({'history': history, 'final': final}, f, ensure_ascii=False, indent=2)

    cm = final.get('confusion_matrix', [[0, 0], [0, 0]])
    with open(confusion_path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['', 'pred_real', 'pred_fake'])
        w.writerow(['true_real', cm[0][0], cm[0][1]])
        w.writerow(['true_fake', cm[1][0], cm[1][1]])

    print(f"Saved metrics to {metrics_path}")
    print(f"Saved confusion matrix to {confusion_path}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    args = parser.parse_args()
    main(args.config)
