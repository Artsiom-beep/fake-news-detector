import torch
import torch.nn as nn
from transformers import AutoModel
from torchvision.models import efficientnet_b0


class TextEncoder(nn.Module):
    def __init__(self, model_name: str):
        super().__init__()
        self.model = AutoModel.from_pretrained(model_name)
        self.hidden_size = self.model.config.hidden_size

    def forward(self, input_ids, attention_mask):
        out = self.model(input_ids=input_ids, attention_mask=attention_mask)
        cls = out.last_hidden_state[:, 0, :]
        return cls


class ImageEncoder(nn.Module):
    def __init__(self):
        super().__init__()
        base = efficientnet_b0(weights=None)
        in_features = base.classifier[1].in_features
        base.classifier = nn.Identity()
        self.backbone = base
        self.hidden_size = in_features

    def forward(self, image):
        return self.backbone(image)


class VideoEncoder(nn.Module):
    def __init__(self, image_encoder: ImageEncoder, hidden_size: int):
        super().__init__()
        self.frame_encoder = image_encoder
        self.temporal = nn.LSTM(
            input_size=self.frame_encoder.hidden_size,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
            bidirectional=True,
        )
        self.hidden_size = hidden_size * 2

    def forward(self, video_frames):
        b, t, c, h, w = video_frames.shape
        x = video_frames.view(b * t, c, h, w)
        frame_feats = self.frame_encoder(x)
        frame_feats = frame_feats.view(b, t, -1)
        out, _ = self.temporal(frame_feats)
        pooled = out.mean(dim=1)
        return pooled


class MultimodalFakeNewsModel(nn.Module):
    def __init__(self, text_model_name: str, fusion_hidden: int = 256, dropout: float = 0.2, text_only: bool = False):
        super().__init__()
        self.text_only = text_only
        self.text_encoder = TextEncoder(text_model_name)
        if not self.text_only:
            self.image_encoder = ImageEncoder()
            self.video_encoder = VideoEncoder(ImageEncoder(), hidden_size=256)
            fusion_in = self.text_encoder.hidden_size + self.image_encoder.hidden_size + self.video_encoder.hidden_size
        else:
            fusion_in = self.text_encoder.hidden_size

        self.head = nn.Sequential(
            nn.Linear(fusion_in, fusion_hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(fusion_hidden, 1),
        )

    def forward(self, input_ids, attention_mask, image, video_frames):
        t = self.text_encoder(input_ids, attention_mask)
        if self.text_only:
            fused = t
        else:
            i = self.image_encoder(image)
            v = self.video_encoder(video_frames)
            fused = torch.cat([t, i, v], dim=1)
        logits = self.head(fused).squeeze(1)
        return logits
