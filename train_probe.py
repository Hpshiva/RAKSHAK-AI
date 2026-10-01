"""
Train a lightweight Linear Probe on frozen CLIP embeddings.
Extracts ViT-L-14 representations for positive (violence/weapon) and negative (normal)
images or frames, and trains a fast classifier with CrossEntropyLoss.
"""

import os
import argparse
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from pathlib import Path
from PIL import Image
import numpy as np

from ai.model import Model
from ai.linear_probe import ProbeClassifier, CLIPLinearProbe

class EmbeddingDataset(Dataset):
    def __init__(self, embeddings, labels):
        self.embeddings = torch.tensor(embeddings, dtype=torch.float32)
        self.labels = torch.tensor(labels, dtype=torch.long)

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, idx):
        return self.embeddings[idx], self.labels[idx]

def extract_embeddings_from_directory(data_dir: str, clip_model: Model):
    """
    Expects data_dir with subdirectories:
      data_dir/
        0_normal/
        1_violence/
    """
    embeddings = []
    labels = []
    classes = sorted([d for d in os.listdir(data_dir) if os.path.isdir(os.path.join(data_dir, d))])
    print(f"Discovered classes: {classes}")

    for class_idx, class_name in enumerate(classes):
        class_folder = os.path.join(data_dir, class_name)
        image_files = [
            f for f in os.listdir(class_folder)
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))
        ]
        print(f"Extracting features for {class_name} ({len(image_files)} images)...")
        
        batch = []
        for img_name in image_files:
            img_path = os.path.join(class_folder, img_name)
            try:
                img = Image.open(img_path).convert("RGB")
                batch.append(np.array(img))
                if len(batch) >= 16:
                    tensors = torch.cat([clip_model.transform_image(b) for b in batch], dim=0)
                    with torch.inference_mode():
                        feats = clip_model.model.encode_image(tensors)
                        feats = feats / feats.norm(dim=-1, keepdim=True)
                    embeddings.extend(feats.cpu().numpy())
                    labels.extend([class_idx] * len(batch))
                    batch = []
            except Exception as e:
                print(f"Skipping {img_path}: {e}")

        if batch:
            tensors = torch.cat([clip_model.transform_image(b) for b in batch], dim=0)
            with torch.inference_mode():
                feats = clip_model.model.encode_image(tensors)
                feats = feats / feats.norm(dim=-1, keepdim=True)
            embeddings.extend(feats.cpu().numpy())
            labels.extend([class_idx] * len(batch))

    return np.array(embeddings), np.array(labels)

def train_probe(data_dir: str, output_path: str = "models/clip_probe.pt", epochs: int = 30, lr: float = 1e-3):
    print("Loading base CLIP model...")
    clip_model = Model()
    print("Extracting feature embeddings...")
    embeddings, labels = extract_embeddings_from_directory(data_dir, clip_model)
    
    if len(embeddings) == 0:
        print("No images found to train probe.")
        return

    dataset = EmbeddingDataset(embeddings, labels)
    dataloader = DataLoader(dataset, batch_size=32, shuffle=True)
    
    num_classes = len(np.unique(labels))
    probe = ProbeClassifier(num_classes=num_classes)
    probe.model.train()
    
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(probe.model.parameters(), lr=lr, weight_decay=1e-2)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    
    print(f"Training probe for {epochs} epochs on {len(embeddings)} samples...")
    for epoch in range(epochs):
        total_loss = 0.0
        correct = 0
        total = 0
        for x, y in dataloader:
            x, y = x.to(probe.device), y.to(probe.device)
            optimizer.zero_grad()
            out = probe.model(x)
            loss = criterion(out, y)
            loss.backward()
            optimizer.step()
            
            total_loss += loss.item() * len(y)
            pred = out.argmax(dim=1)
            correct += (pred == y).sum().item()
            total += len(y)
            
        scheduler.step()
        acc = 100.0 * correct / total
        if (epoch + 1) % 5 == 0 or epoch == epochs - 1:
            print(f"Epoch [{epoch+1}/{epochs}] Loss: {total_loss/total:.4f} Acc: {acc:.2f}%")

    probe.save(output_path)
    print(f"Training finished. Model saved to {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train CLIP Linear Probe on Violence Dataset")
    parser.add_argument("--data_dir", type=str, default="datasets/violence_frames", help="Path to labeled data dir")
    parser.add_argument("--output", type=str, default="models/clip_probe.pt", help="Path to save probe weights")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--lr", type=float, default=1e-3)
    args = parser.parse_args()
    
    if os.path.exists(args.data_dir):
        train_probe(args.data_dir, args.output, args.epochs, args.lr)
    else:
        print(f"Directory {args.data_dir} does not exist yet. Please place your training frames into:")
        print(f"  {args.data_dir}/0_normal/")
        print(f"  {args.data_dir}/1_violence/")
