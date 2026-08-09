import cv2
from app import generate_webcam_frames, cameras, ZeroLatencyCamera
import time

print("Testing generate_webcam_frames...")
gen = generate_webcam_frames(0)

print("Yielding 10 frames...")
for i in range(10):
    try:
        frame_bytes = next(gen)
        print(f"Frame {i}: Got {len(frame_bytes)} bytes")
    except Exception as e:
        print(f"Exception: {e}")
        break

print("Done. Cleaning up.")
if 0 in cameras and cameras[0]:
    cameras[0].release()
