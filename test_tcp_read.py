import cv2
import time
cap = cv2.VideoCapture("tcp://127.0.0.1:12346", cv2.CAP_FFMPEG)
if not cap.isOpened():
    print("Failed")
    exit(1)
ret, frame = cap.read()
if ret:
    print(f"Read frame shape: {frame.shape}")
cap.release()
