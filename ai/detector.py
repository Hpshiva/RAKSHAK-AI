import cv2
import os
import threading
from datetime import datetime
from database import save_detection
from ultralytics import YOLO

# ==========================================
# LOAD YOLO MODEL
# ==========================================

print("\n======================================")
print(" Loading Rakshak AI Detector...")
print("======================================")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "models", "yolov8x.pt")
model = YOLO(MODEL_PATH)

print(" YOLO Model Loaded Successfully")

from ai.model import Model
print(" Loading Violence Detection Model...")
violence_model = Model()
print(" Violence Detection Model Loaded Successfully")

print("======================================\n")

# ==========================================
# GLOBALS & MULTI-CAMERA STATE
# ==========================================

# We don't need ai_lock for predict anymore if it's strictly single-threaded in the worker,
# but keeping it for safety if needed. We use ai_worker_lock for queueing.
ai_worker_lock = threading.Lock()
latest_frames_for_ai = {}

# Global events list
detections = []
MAX_DETECTIONS = 15

# Global robot status
robot_dispatch = False
dispatch_camera = None

# Labels considered violent or threatening
VIOLENCE_LABELS = {
    'fight on a street', 'street violence', 'violence in office', 'fire in office',
    'person holding a gun', 'person holding a knife', 'weapon', 'armed robbery',
    'physical assault', 'explosion'
}

# State per camera
class CameraState:
    def __init__(self, name):
        self.name = name
        self.person_count = 0
        self.frame_count = 0
        self.frame_count_ai = 0
        self.last_violence_label = "Unknown"
        self.last_violence_confidence = 0.0
        self.current_threat = "LOW"
        self.cached_boxes = []

camera_states = {}

def get_camera_state(cam_id, cam_name="Camera"):
    if cam_id not in camera_states:
        camera_states[cam_id] = CameraState(cam_name)
    return camera_states[cam_id]

# ==========================================
# COLORS
# ==========================================
GREEN = (0, 255, 0)
ORANGE = (0, 165, 255)
RED = (0, 0, 255)
WHITE = (255, 255, 255)
BLACK = (25, 25, 25)

# ==========================================
# THREAT ENGINE
# ==========================================
def get_threat_level(count):
    if count >= 5:
        return "HIGH", RED
    elif count >= 3:
        return "MEDIUM", ORANGE
    return "LOW", GREEN

# ==========================================
# EVENT LOGGER
# ==========================================
def add_detection(label, confidence, threat, camera_name):
    global detections
    event = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "label": f"{label.title()} Detected",
        "confidence": confidence,
        "camera": camera_name,
        "location": "PM SHRI KV",
        "threat": threat
    }
    
    if len(detections) == 0:
        detections.insert(0, event)
        return
        
    latest = detections[0]
    if (latest["label"] != event["label"] or latest["threat"] != event["threat"] or latest["confidence"] != event["confidence"]):
        detections.insert(0, event)
    detections = detections[:MAX_DETECTIONS]

# ==========================================
# DRAW BOUNDING BOX
# ==========================================
def draw_box(frame, coords, confidence, color, label):
    x1, y1, x2, y2 = coords
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    cv2.rectangle(frame, (x1, y1 - 28), (x2, y1), color, -1)
    cv2.putText(frame, f"{label.title()} {confidence:.1f}%", (x1 + 5, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 2)

# ==========================================
# ASYNC AI WORKER THREAD
# ==========================================
import time
def ai_worker():
    while True:
        frames_to_process = []
        with ai_worker_lock:
            for cid, frame in latest_frames_for_ai.items():
                frames_to_process.append((cid, frame))
            latest_frames_for_ai.clear()
            
        if not frames_to_process:
            time.sleep(0.01)
            continue
            
        for cid, frame in frames_to_process:
            state = get_camera_state(cid)
            state.frame_count_ai += 1
            
            try:
                # 1. Violence / Threat Detection (every 5 frames to save CPU)
                if state.frame_count_ai % 5 == 0:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    violence_prediction = violence_model.predict(image=rgb_frame)
                    state.last_violence_label = violence_prediction['label']
                    state.last_violence_confidence = violence_prediction['confidence']
                    
                    if state.last_violence_label in VIOLENCE_LABELS:
                        add_detection(state.last_violence_label, round(state.last_violence_confidence * 100, 1), "CRITICAL", state.name)
                        save_detection(label=state.last_violence_label, confidence=round(state.last_violence_confidence * 100, 1), severity="CRITICAL", camera=state.name)

                # 2. YOLO Object Detection
                state.person_count = 0
                results = model.predict(source=frame, conf=0.45, imgsz=640, verbose=False)
                result = results[0]

                new_boxes = []
                for box in result.boxes:
                    cls = int(box.cls[0])
                    class_name = model.names[cls]
                    confidence = round(float(box.conf[0]) * 100, 1)
                    coords = tuple(map(int, box.xyxy[0]))

                    if class_name == "person":
                        state.person_count += 1
                        threat, color = get_threat_level(state.person_count)
                        new_boxes.append((coords, confidence, color, class_name))
                        
                        add_detection(class_name, confidence, threat, state.name)
                        save_detection(label=class_name, confidence=confidence, severity=threat, camera=state.name)
                    else:
                        new_boxes.append((coords, confidence, GREEN, class_name))
                
                state.cached_boxes = new_boxes
            except Exception as e:
                print(f"AI Worker Error on cam {cid}:", e)

# Start the background worker
worker_thread = threading.Thread(target=ai_worker, daemon=True)
worker_thread.start()

# ==========================================
# MAIN DETECTION FUNCTION (INSTANT)
# ==========================================
def detect(frame, camera_id="0", camera_name="Main Gate"):
    # Mirror if webcam
    if str(camera_id) == "0":
        frame = cv2.flip(frame, 1)

    global robot_dispatch, dispatch_camera

    state = get_camera_state(camera_id, camera_name)
    state.frame_count += 1

    try:
        # Pass the latest frame to the AI worker
        with ai_worker_lock:
            latest_frames_for_ai[camera_id] = frame.copy()

        # Draw the latest known bounding boxes instantly
        for coords, confidence, color, class_name in state.cached_boxes:
            draw_box(frame, coords, confidence, color, class_name)

        # Threat Assessment
        threat, _ = get_threat_level(state.person_count)
        
        if state.last_violence_label in VIOLENCE_LABELS:
            threat = "CRITICAL"
            cv2.putText(frame, f"CRITICAL: {state.last_violence_label.upper()}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, RED, 3)

        state.current_threat = threat

        # Global robot logic: if ANY camera is high/critical, dispatch robot
        if threat in ["HIGH", "CRITICAL"]:
            robot_dispatch = True
            dispatch_camera = camera_name

        return frame

    except Exception as e:
        print(f"Detector Error on cam {camera_id}:", e)
        return frame

# ==========================================
# GET ROBOT STATUS
# ==========================================
def get_robot_status():
    total_people = sum(s.person_count for s in camera_states.values())
    highest_threat = "LOW"
    for s in camera_states.values():
        if s.current_threat == "CRITICAL":
            highest_threat = "CRITICAL"
            break
        elif s.current_threat == "HIGH":
            highest_threat = "HIGH"
        elif s.current_threat == "MEDIUM" and highest_threat == "LOW":
            highest_threat = "MEDIUM"

    return {
        "dispatch": robot_dispatch,
        "camera": dispatch_camera,
        "threat": highest_threat,
        "people": total_people
    }

# ==========================================
# RESET DETECTIONS
# ==========================================
def clear_detections():
    global detections, robot_dispatch, dispatch_camera
    detections.clear()
    robot_dispatch = False
    dispatch_camera = None
    for s in camera_states.values():
        s.person_count = 0
        s.current_threat = "LOW"