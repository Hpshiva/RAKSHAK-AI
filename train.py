from ultralytics import YOLO
import os

# ==========================================
# TRAINING CONFIGURATION
# ==========================================
# 1. Provide the path to your dataset configuration file
#    (e.g., 'dataset.yaml' containing train/val image paths and class names)
DATASET_YAML = "dataset.yaml"

# 2. Choose the base model to start training from. 
#    Using a pre-trained model like yolov8x.pt is recommended (Transfer Learning)
BASE_MODEL = "yolov8x.pt" 

# 3. Training parameters
EPOCHS = 50           # Number of times the model sees the entire dataset
BATCH_SIZE = 16       # Number of images processed at once
IMAGE_SIZE = 640      # Resize images to 640x640 before training

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
    print(f"Loading base model: {BASE_MODEL}")
    model = YOLO(BASE_MODEL)

    # Train the model
    print("Starting training...")
    results = model.train(
        data=DATASET_YAML,
        epochs=EPOCHS,
        imgsz=IMAGE_SIZE,
        batch=BATCH_SIZE,
        name="rakshak_custom_model", # the folder name where weights will be saved (runs/detect/rakshak_custom_model/weights/best.pt)
        patience=10 # Stop early if no improvement for 10 epochs
    )

    print("======================================")
    print("✅ Training Complete!")
    print("Your new trained weights are saved in: runs/detect/rakshak_custom_model/weights/best.pt")
    print("To use this model, update ai/detector.py to load this new path instead of yolov8m.pt")
    print("======================================")

if __name__ == '__main__':
    train_custom_model()
