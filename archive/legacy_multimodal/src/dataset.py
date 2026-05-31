from typing import Optional
import cv2
import pandas as pd
import numpy as np
import torch
from torch.utils.data import Dataset
from PIL import Image
from torchvision import transforms
from transformers import AutoTokenizer


class MultimodalNewsDataset(Dataset):
    def __init__(
        self,
        csv_path: str,
        tokenizer_name: str,
        max_text_len: int = 256,
        image_size: int = 224,
        video_frames: int = 8,
        max_samples: Optional[int] = None,
    ):
        self.df = pd.read_csv(csv_path)
        self.df = self.df.fillna('')
        if max_samples is not None and len(self.df) > max_samples:
            self.df = self.df.sample(n=max_samples, random_state=42).reset_index(drop=True)
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
        self.max_text_len = max_text_len
        self.video_frames = video_frames
        self.image_transform = transforms.Compose([
            transforms.Resize((image_size, image_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    def __len__(self):
        return len(self.df)

    def _load_image(self, path: str) -> torch.Tensor:
        if not path:
            return torch.zeros(3, 224, 224)
        try:
            img = Image.open(path).convert('RGB')
            return self.image_transform(img)
        except Exception:
            return torch.zeros(3, 224, 224)

    def _sample_video_frames(self, video_path: str) -> torch.Tensor:
        if not video_path:
            return torch.zeros(self.video_frames, 3, 224, 224)
        cap = cv2.VideoCapture(video_path)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_count <= 0:
            cap.release()
            return torch.zeros(self.video_frames, 3, 224, 224)

        indices = np.linspace(0, max(frame_count - 1, 0), self.video_frames).astype(int)
        frames = []
        idx_set = set(indices.tolist())
        current = 0

        while cap.isOpened() and len(frames) < self.video_frames:
            ret, frame = cap.read()
            if not ret:
                break
            if current in idx_set:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil = Image.fromarray(frame)
                frames.append(self.image_transform(pil))
            current += 1

        cap.release()
        while len(frames) < self.video_frames:
            frames.append(torch.zeros(3, 224, 224))
        return torch.stack(frames, dim=0)

    def __getitem__(self, idx: int):
        row = self.df.iloc[idx]

        full_text = str(row.get('text', '')) + ' ' + str(row.get('transcript', ''))
        encoded = self.tokenizer(
            full_text,
            padding='max_length',
            truncation=True,
            max_length=self.max_text_len,
            return_tensors='pt',
        )

        image = self._load_image(str(row.get('image_path', '')))
        video_frames = self._sample_video_frames(str(row.get('video_path', '')))
        label = torch.tensor(int(row['label']), dtype=torch.float32)

        return {
            'input_ids': encoded['input_ids'].squeeze(0),
            'attention_mask': encoded['attention_mask'].squeeze(0),
            'image': image,
            'video_frames': video_frames,
            'label': label,
        }
