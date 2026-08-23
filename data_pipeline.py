import os
import cv2
import shutil
import random
from pathlib import Path

# ==========================================
# DATA PIPELINE CONFIGURATION
# ==========================================
RAW_DATA_DIR = Path("raw_data")
DATASET_DIR = Path("datasets/weapons")
CLASSES = ["person", "gun", "knife"]
SPLIT_RATIO = {"train": 0.8, "val": 0.1, "test": 0.1}
FRAME_EXTRACTION_RATE = 1  # extract 1 frame per second for videos

def create_directory_structure():
    """Create the YOLO dataset directory structure."""
    print("Creating dataset directory structure...")
    for split in ["train", "val", "test"]:
        (DATASET_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (DATASET_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)
    
    # Create dataset.yaml
    yaml_content = f"""# Dataset configuration for YOLOv8 Custom Training
# Reference: https://docs.ultralytics.com/datasets/detect/

# Paths to the training, validation, and test images
path: {DATASET_DIR.absolute()}
train: images/train
val: images/val
test: images/test

# Number of classes
nc: {len(CLASSES)}

# Class names
names:
"""
    for i, cls in enumerate(CLASSES):
        yaml_content += f"  {i}: {cls}\n"
        
    with open("dataset.yaml", "w") as f:
        f.write(yaml_content)
    print("dataset.yaml created/updated.")

def extract_frames(video_path, output_dir, label_dir, base_filename):
    """Extract frames from a video at a specified frame rate."""
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0:
        return []
    
    frame_interval = int(fps / FRAME_EXTRACTION_RATE)
    frame_count = 0
    extracted_frames = []
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        if frame_count % frame_interval == 0:
            frame_filename = f"{base_filename}_frame_{frame_count}.jpg"
            frame_path = output_dir / frame_filename
            cv2.imwrite(str(frame_path), frame)
            extracted_frames.append(frame_filename)
            
            # Create an empty label file if none exists, just to prevent YOLO from complaining,
            # though usually you would want real bounding boxes here.
            label_filename = f"{base_filename}_frame_{frame_count}.txt"
            label_path = label_dir / label_filename
            if not label_path.exists():
                with open(label_path, 'w') as f:
                    pass # Empty label (no objects)
                    
        frame_count += 1
        
    cap.release()
    return extracted_frames

def process_data():
    """Process all data in the raw_data directory and split it."""
    if not RAW_DATA_DIR.exists():
        print(f"Creating {RAW_DATA_DIR} directory. Please put your raw images/videos here.")
        RAW_DATA_DIR.mkdir()
        return

    all_files = [f for f in RAW_DATA_DIR.iterdir() if f.is_file() and f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.mp4', '.avi', '.mov']]
    
    if not all_files:
        print(f"No media files found in {RAW_DATA_DIR}. Please add your images/videos.")
        return

    # Shuffle for random split
    random.seed(42)
    random.shuffle(all_files)
    
    train_split = int(len(all_files) * SPLIT_RATIO["train"])
    val_split = train_split + int(len(all_files) * SPLIT_RATIO["val"])
    
    splits = {
        "train": all_files[:train_split],
        "val": all_files[train_split:val_split],
        "test": all_files[val_split:]
    }
    
    for split_name, files in splits.items():
        print(f"Processing {len(files)} files for '{split_name}' split...")
        img_dir = DATASET_DIR / "images" / split_name
        lbl_dir = DATASET_DIR / "labels" / split_name
        
        for file in files:
            base_name = file.stem
            # Check if it's a video
            if file.suffix.lower() in ['.mp4', '.avi', '.mov']:
                extract_frames(file, img_dir, lbl_dir, base_name)
            else:
                # It's an image, copy it
                shutil.copy(file, img_dir / file.name)
                # Look for a matching label file in raw_data
                label_file = RAW_DATA_DIR / f"{base_name}.txt"
                if label_file.exists():
                    shutil.copy(label_file, lbl_dir / label_file.name)
                else:
                    # Create empty label
                    with open(lbl_dir / f"{base_name}.txt", 'w') as f:
                        pass

    print("Data pipeline finished processing.")

if __name__ == '__main__':
    create_directory_structure()
    process_data()
