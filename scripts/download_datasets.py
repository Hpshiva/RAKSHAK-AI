import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

def print_instructions():
    print("\n=======================================================")
    print(" Rakshak AI Dataset Downloader & Fine-Tuning Guide")
    print("=======================================================")
    print("\nTo fine-tune or evaluate the violence detection model on real-world datasets:")
    print("\n1. Download Public Datasets:")
    print("   • Real Life Violence Situations Dataset (Kaggle):")
    print("     https://www.kaggle.com/datasets/mohamedmustafa/real-life-violence-situations-dataset")
    print("   • RWF-2000 CCTV Violence Dataset:")
    print("     https://github.com/macaodha/RWF-2000")
    print("   • Roboflow Weapon / Gun Detection Dataset:")
    print("     https://universe.roboflow.com/search?q=weapon+detection")

    print("\n2. Directory Layout Setup:")
    print("   Place extracted images into:")
    print(f"   {os.path.join(BASE_DIR, 'dataset', 'val', 'violence')}")
    print(f"   {os.path.join(BASE_DIR, 'dataset', 'val', 'non_violence')}")

    print("\n3. Run Accuracy Benchmark:")
    print("   python3 scripts/train_violence_model.py")
    print("=======================================================\n")

if __name__ == "__main__":
    dataset_dir = os.path.join(BASE_DIR, "dataset", "val")
    os.makedirs(os.path.join(dataset_dir, "violence"), exist_ok=True)
    os.makedirs(os.path.join(dataset_dir, "non_violence"), exist_ok=True)
    print_instructions()
