import cv2
import time
start = time.time()
available = []
for i in range(5):
    t0 = time.time()
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        ret, _ = cap.read()
        if ret:
            available.append(i)
        cap.release()
    print(f"Cam {i} took {time.time()-t0:.2f}s")
print(f"Available: {available}, Total time: {time.time()-start:.2f}s")
