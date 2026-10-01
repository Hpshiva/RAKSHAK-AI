import cv2
import threading
import time
import subprocess

def run_ffmpeg():
    subprocess.run([
        "./tools/ffmpeg", "-v", "error", "-re", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30",
        "-vf", "hflip",
        "-c:v", "rawvideo", "-pix_fmt", "bgr24",
        "-f", "nut", "tcp://127.0.0.1:12345?listen=1"
    ])

t = threading.Thread(target=run_ffmpeg, daemon=True)
t.start()

time.sleep(2)
cap = cv2.VideoCapture("tcp://127.0.0.1:12345", cv2.CAP_FFMPEG)
if not cap.isOpened():
    print("Failed")
    exit(1)

ret, frame = cap.read()
if ret:
    print(f"Success! Frame shape: {frame.shape}")
cap.release()
