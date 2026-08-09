import cv2
import os
import time
from datetime import datetime
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
frame = np.zeros((480, 640, 3), dtype=np.uint8)

try:
    snapshot_dir = os.path.join(BASE_DIR, "rakshak ai")
    os.makedirs(snapshot_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filepath = os.path.join(snapshot_dir, f"test_{timestamp}.jpg")
    cv2.imwrite(filepath, frame)
    
    from database import save_snapshot
    save_snapshot(filepath)
    print(f"Success! Saved to {filepath}")
except Exception as e:
    print(f"Error: {e}")
