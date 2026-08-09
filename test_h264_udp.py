import cv2
import threading
import time
import subprocess

def run_ffmpeg():
    subprocess.run([
        "./tools/ffmpeg", "-v", "error", "-re", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency", "-b:v", "2M", "-g", "15",
        "-f", "mpegts", "udp://127.0.0.1:12345?pkt_size=1316"
    ])

t = threading.Thread(target=run_ffmpeg, daemon=True)
t.start()

time.sleep(2)
cap = cv2.VideoCapture("udp://127.0.0.1:12345?fifo_size=5000000&overrun_nonfatal=1", cv2.CAP_FFMPEG)
if not cap.isOpened():
    print("Failed to open UDP stream")
    exit(1)

frames = 0
start = time.time()
while time.time() - start < 3:
    ret, frame = cap.read()
    if ret:
        frames += 1
print(f"Success! Read {frames} frames.")
cap.release()
