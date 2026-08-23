from ultralytics import YOLO
import os

# ==========================================
# TRAINING CONFIGURATION
# ==========================================
# 1. Provide the path to your dataset configuration file
#    (e.g., 'dataset.yaml' containing train/val image paths and class names)
DATASET_YAML = "violence detection.v4i.yolov8/data.yaml"

# 2. Choose the base model to start training from. 
#    Using a pre-trained model like yolov8x.pt is recommended (Transfer Learning)
BASE_MODEL = "yolov8n.pt"

# 3. Training parameters
EPOCHS = 10
BATCH_SIZE = 8
IMAGE_SIZE = 320
RESUME = True # Set to True to resume training from the last checkpoint

def train_custom_model():
    print("======================================")
    print(" Starting YOLOv8 Training Pipeline")
    print("======================================")

    # Check if dataset.yaml exists
    if not os.path.exists(DATASET_YAML):
        print(f"❌ Error: {DATASET_YAML} not found!")
        print("Please create it and organize your dataset first.")
        print("Refer to the YOLO documentation for formatting: https://docs.ultralytics.com/datasets/detect/")
        return

    # Load a model
    model_path = BASE_MODEL
    if RESUME:
        model_path = "runs/detect/rakshak_custom_model-6/weights/last.pt"
        if not os.path.exists(model_path):
            print(f"❌ Error: Checkpoint {model_path} not found. Cannot resume.")
            return
        print(f"Resuming training from checkpoint: {model_path}")
    else:
        print(f"Loading base model: {model_path}")
    
    model = YOLO(model_path)

    print("Starting training on CPU...")
    results = model.train(
        data=DATASET_YAML,
        epochs=EPOCHS,
        imgsz=IMAGE_SIZE,
        batch=BATCH_SIZE, # Might need to lower this to 4 or 2 if CPU RAM fills up
        name="rakshak_custom_model", 
        patience=20,
        cache=True,
        close_mosaic=10,
        resume=RESUME,
        device="cpu", # Explicitly set to CPU
        amp=False, # Mixed precision is mainly for GPUs, disabling for CPU
        # Data Augmentation parameters
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        degrees=10.0,
        translate=0.1,
        scale=0.5,
        shear=0.0,
        perspective=0.0,
        flipud=0.0,
        fliplr=0.5,
        mosaic=1.0,
        mixup=0.1,
        copy_paste=0.0
    )

    print("======================================")
    print("✅ Training Complete!")
    print("Your new trained weights are saved in: runs/detect/rakshak_custom_model/weights/best.pt")
    print("To use this model, update ai/detector.py to load this new path instead of yolov8x.pt")
    print("======================================")

if __name__ == '__main__':
    train_custom_model()
