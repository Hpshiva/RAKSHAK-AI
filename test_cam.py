import cv2
import time
from app import ZeroLatencyCamera

print("Starting ZeroLatencyCamera...")
cam = ZeroLatencyCamera(0)
time.sleep(2)

success, frame = cam.read()
print(f"Read success: {success}, Frame type: {type(frame)}")
if success and frame is not None:
    print(f"Frame shape: {frame.shape}")
    cv2.imwrite("test_frame.jpg", frame)
    print("Saved test_frame.jpg")
else:
    print("Failed to get frame!")
    
cam.release()
print("Camera released.")
