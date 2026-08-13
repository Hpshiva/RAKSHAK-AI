import os
import sys
import torch
import yaml
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

def print_header(title):
    print("\n" + "=" * 50)
    print(f" {title}")
    print("=" * 50)

def evaluate_openclip_accuracy(dataset_dir):
    """
    Evaluates current OpenCLIP zero-shot classification on a test dataset directory.
    dataset_dir structure:
      dataset_dir/
         violence/ (images)
         non_violence/ (images)
    """
    from ai.model import Model
    print_header("Evaluating OpenCLIP Model Baseline Accuracy")
    
    if not os.path.exists(dataset_dir):
        print(f"[Warning] Dataset directory '{dataset_dir}' not found.")
        print("To run accuracy evaluation, download RWF-2000 or Real Life Violence dataset into dataset/ directory.")
        return

    model = Model()
    correct = 0
    total = 0

    categories = ["violence", "non_violence"]
    for category in categories:
        cat_path = os.path.join(dataset_dir, category)
        if not os.path.exists(cat_path):
            continue
            
        for img_name in os.listdir(cat_path):
            if not img_name.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue
            
            img_file = os.path.join(cat_path, img_name)
            import cv2
            frame = cv2.imread(img_file)
            if frame is None:
                continue

            res = model.predict(frame)
            predicted_label = res["label"]
            
            is_violence = (category == "violence")
            predicted_violence = (predicted_label != "normal / peaceful activity")

            if is_violence == predicted_violence:
                correct += 1
            total += 1

    if total > 0:
        accuracy = (correct / total) * 100
        print(f"\n📊 Evaluation Results: Total Samples = {total}")
        print(f"✅ Accuracy: {accuracy:.2f}%")
    else:
        print("No valid images found for evaluation.")

if __name__ == "__main__":
    print_header("Rakshak AI - Model Accuracy & Training Manager")
    dataset_path = os.path.join(BASE_DIR, "dataset", "val")
    evaluate_openclip_accuracy(dataset_path)
