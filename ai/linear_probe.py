import os
import torch
import torch.nn as nn
import numpy as np
from pathlib import Path

class CLIPLinearProbe(nn.Module):
    """
    Lightweight Linear Probe / MLP classification head on top of frozen CLIP embeddings.
    Provides fast, domain-adapted inference for CCTV footage without requiring
    expensive end-to-end Vision Transformer fine-tuning.
    """
    def __init__(self, embed_dim: int = 768, num_classes: int = 2, hidden_dim: int = 256):
        super().__init__()
        self.classifier = nn.Sequential(
            nn.Linear(embed_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.3),
            nn.Linear(hidden_dim, num_classes)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Normalize embeddings if not already normalized
        x = x / (x.norm(dim=-1, keepdim=True) + 1e-7)
        return self.classifier(x)

class ProbeClassifier:
    """Wrapper to load, train, and run inference using a trained Linear Probe."""
    def __init__(self, model_path: str = None, num_classes: int = 2, device: str = None):
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)
            
        self.num_classes = num_classes
        self.model = CLIPLinearProbe(embed_dim=768, num_classes=num_classes).to(self.device)
        self.is_trained = False
        
        if model_path and os.path.isfile(model_path):
            self.load(model_path)

    def load(self, model_path: str):
        try:
            state_dict = torch.load(model_path, map_location=self.device)
            self.model.load_state_dict(state_dict)
            self.model.eval()
            self.is_trained = True
            print(f"Loaded trained CLIP linear probe from {model_path}")
        except Exception as e:
            print(f"Warning: Failed to load linear probe from {model_path}: {e}")
            self.is_trained = False

    def save(self, model_path: str):
        os.makedirs(os.path.dirname(os.path.abspath(model_path)), exist_ok=True)
        torch.save(self.model.state_dict(), model_path)
        print(f"Saved CLIP linear probe to {model_path}")

    @torch.inference_mode()
    def predict_embedding(self, embedding: torch.Tensor) -> tuple[int, float]:
        """
        Accepts normalized CLIP embedding tensor [1, 768] or [N, 768].
        Returns (predicted_class_index, confidence_score).
        """
        if not self.is_trained:
            return 0, 0.0
        self.model.eval()
        if embedding.ndim == 1:
            embedding = embedding.unsqueeze(0)
        embedding = embedding.to(self.device)
        logits = self.model(embedding)
        probs = torch.softmax(logits, dim=-1)
        conf, pred_idx = probs.max(dim=-1)
        return pred_idx.item(), conf.item()
