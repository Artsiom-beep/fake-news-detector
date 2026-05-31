import argparse
import numpy as np
import torch
from torch.utils.data import DataLoader
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, confusion_matrix, classification_report, f1_score

from dataset import MultimodalNewsDataset
from models import MultimodalFakeNewsModel
from utils import load_config


def _metrics_from_probs(y_true, probs, threshold: float):
    y_pred = (probs >= threshold).astype(int)
    acc = accuracy_score(y_true, y_pred)
    p, r, f1, _ = precision_recall_fscore_support(
        y_true,
        y_pred,
        average='binary',
        pos_label=1,
        labels=[0, 1],
        zero_division=0,
    )
    macro_f1 = f1_score(y_true, y_pred, average='macro', labels=[0, 1], zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=[0, 1])
    report = classification_report(
        y_true,
        y_pred,
        labels=[0, 1],
        target_names=['real', 'fake'],
        zero_division=0,
    )
    return {
        'threshold': float(threshold),
        'accuracy': float(acc),
        'precision': float(p),
        'recall': float(r),
        'f1': float(f1),
        'macro_f1': float(macro_f1),
        'confusion_matrix': cm.tolist(),
        'classification_report': report,
    }


@torch.no_grad()
def evaluate(model, loader, device, verbose: bool = False, threshold: float = 0.5, tune_threshold: bool = False):
    model.eval()
    y_true, probs = [], []

    for batch in loader:
        input_ids = batch['input_ids'].to(device)
        attention_mask = batch['attention_mask'].to(device)
        image = batch['image'].to(device)
        video_frames = batch['video_frames'].to(device)
        labels = batch['label'].to(device)

        logits = model(input_ids, attention_mask, image, video_frames)
        batch_probs = torch.sigmoid(logits).cpu().numpy()

        probs.extend(batch_probs.tolist())
        y_true.extend(labels.long().cpu().numpy().tolist())

    y_true = np.asarray(y_true)
    probs = np.asarray(probs)

    best = _metrics_from_probs(y_true, probs, threshold)
    if tune_threshold:
        candidates = np.linspace(0.1, 0.9, 17)
        for thr in candidates:
            cur = _metrics_from_probs(y_true, probs, float(thr))
            if cur['macro_f1'] > best['macro_f1']:
                best = cur

    if verbose:
        print(f"Threshold: {best['threshold']:.2f}")
        print('Confusion matrix:\n', np.array(best['confusion_matrix']))
        print('\nClassification report:\n', best['classification_report'])
    return best


def main(config_path: str, threshold: float = 0.5):
    cfg = load_config(config_path)
    device = torch.device(cfg.get('device', 'cpu'))

    ds = MultimodalNewsDataset(
        cfg['paths']['test_csv'],
        tokenizer_name=cfg['model']['text_model_name'],
        max_text_len=cfg['model']['max_text_len'],
        image_size=cfg['model']['image_size'],
        video_frames=cfg['model']['video_frames'],
        max_samples=cfg['model'].get('test_max_samples'),
    )
    loader = DataLoader(ds, batch_size=cfg['train']['batch_size'], shuffle=False, num_workers=cfg['train']['num_workers'])

    model = MultimodalFakeNewsModel(
        text_model_name=cfg['model']['text_model_name'],
        fusion_hidden=cfg['model']['fusion_hidden'],
        dropout=cfg['model']['dropout'],
        text_only=cfg['model'].get('text_only', False),
    ).to(device)

    state = torch.load(cfg['train']['save_path'], map_location=device)
    model.load_state_dict(state)

    metrics = evaluate(model, loader, device, threshold=threshold)
    print('Test metrics:', metrics)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=str, required=True)
    parser.add_argument('--threshold', type=float, default=0.5)
    args = parser.parse_args()
    main(args.config, threshold=args.threshold)
