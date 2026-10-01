from ultralytics import YOLO
import os
import torch

# ==========================================
# TRAINING CONFIGURATION (HIGH-FIDELITY YOLOv8)
# ==========================================
DATASET_YAML = "violence detection1.v4i.yolov8/data.yaml"
if not os.path.exists(DATASET_YAML):
    DATASET_YAML = "violence detection.v4i.yolov8/data.yaml"
if not os.path.exists(DATASET_YAML) and os.path.exists("dataset.yaml"):
    DATASET_YAML = "dataset.yaml"

BASE_MODEL = "models/yolov8m.pt" if os.path.exists("models/yolov8m.pt") else "yolov8n.pt"

# Auto-detect best hardware accelerator
if torch.cuda.is_available():
    TRAIN_DEVICE = 0
    MIXED_PRECISION = True
elif torch.backends.mps.is_available():
    TRAIN_DEVICE = "mps"
    MIXED_PRECISION = False
else:
    TRAIN_DEVICE = "cpu"
    MIXED_PRECISION = False

EPOCHS = 5
BATCH_SIZE = 8 if TRAIN_DEVICE != "cpu" else 4
IMAGE_SIZE = 640
RESUME = False


def train_custom_model(epochs=EPOCHS, batch=BATCH_SIZE, device=TRAIN_DEVICE, resume=RESUME):
    print("======================================")
    print(f" Starting High-Resolution YOLO Training ({IMAGE_SIZE}x{IMAGE_SIZE})")
    print(f" Target Device: {device} (Mixed Precision: {MIXED_PRECISION})")
    print(f" Using Dataset: {DATASET_YAML}")
    print(f" Epochs: {epochs} | Batch Size: {batch}")
    print("======================================")

    if not os.path.exists(DATASET_YAML):
        print(f"❌ Error: Dataset config {DATASET_YAML} not found!")
        print("Please organize your dataset and ensure data.yaml exists.")
        return

    model_path = BASE_MODEL
    checkpoint_path = "runs/detect/rakshak_custom_model/weights/last.pt"
    if resume and os.path.exists(checkpoint_path):
        model_path = checkpoint_path
        print(f"Resuming training from checkpoint: {model_path}")
    else:
        print(f"Loading base model: {model_path}")

    model = YOLO(model_path)

    results = model.train(
        data=DATASET_YAML,
        epochs=epochs,
        imgsz=IMAGE_SIZE,
        batch=batch,
        name="rakshak_custom_model",
        exist_ok=True,
        patience=15,
        cache=False,
        workers=2,
        close_mosaic=min(2, epochs),
        resume=resume and os.path.exists(checkpoint_path),
        device=device,
        amp=MIXED_PRECISION,
        # Multi-Scale & CCTV Augmentations
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        degrees=12.0,
        translate=0.1,
        scale=0.5,
        shear=2.0,
        perspective=0.0005,
        flipud=0.0,
        fliplr=0.5,
        mosaic=1.0,
        mixup=0.15,
        copy_paste=0.1,
    )

    best_pt = "runs/detect/rakshak_custom_model/weights/best.pt"
    if os.path.exists(best_pt):
        os.makedirs("models", exist_ok=True)
        import shutil
        target_model = "models/violence_yolov8.pt"
        shutil.copy(best_pt, target_model)
        print(f" Copied best model to {target_model}")

    print("======================================")
    print("✅ Training Complete!")
    print(f"Your new trained weights are saved in: {best_pt}")
    print("======================================")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Train Rakshak YOLOv8 Model")
    parser.add_argument("--epochs", type=int, default=EPOCHS, help="Number of training epochs")
    parser.add_argument("--batch", type=int, default=BATCH_SIZE, help="Batch size")
    parser.add_argument("--device", type=str, default=str(TRAIN_DEVICE), help="Device (mps, cuda, cpu)")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    args = parser.parse_args()

    train_custom_model(epochs=args.epochs, batch=args.batch, device=args.device, resume=args.resume)
