import cv2
import os
import threading
import time
import pyttsx3
from datetime import datetime
from database import save_detection, should_save_detection
from ultralytics import YOLO
from ai.face_recognition import FaceRecognizer

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

print(" Loading Face Recognition Model...")
face_recognizer = FaceRecognizer()
faces_dir = os.path.join(BASE_DIR, "faces")
os.makedirs(faces_dir, exist_ok=True)
face_recognizer.load_faces(faces_dir)

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

# Global tracking
robot_dispatch = False
dispatch_camera = None
global_last_screenshot_time = 0

# Labels considered violent or threatening
VIOLENCE_LABELS = {
    'fight on a street', 'street violence', 'violence in office', 'fire in office', 'fire on a street',
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
        self.last_audio_alert_time = 0
        self.screenshot_count_this_event = 0
        self.last_violence_time = 0
        self.last_screenshot_trigger_time = 0
        self.last_recognized_name = None
        self.last_recognized_time = 0

camera_states = {}

def get_camera_state(cam_id, cam_name="Camera"):
    if cam_id not in camera_states:
        camera_states[cam_id] = CameraState(cam_name)
    return camera_states[cam_id]

def remove_camera(cam_id):
    if cam_id in camera_states:
        del camera_states[cam_id]
        
    any_critical = any(s.current_threat in ["HIGH", "CRITICAL"] for s in camera_states.values())
    global robot_dispatch, dispatch_camera
    robot_dispatch = any_critical
    if not robot_dispatch:
        dispatch_camera = None

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
def get_threat_level(count, is_violent=False):
    if is_violent:
        return "CRITICAL", RED
    return "LOW", GREEN

# ==========================================
# EVENT LOGGER
# ==========================================
last_memory_alert = {} # label -> timestamp

def add_detection(label, confidence, threat, camera_name):
    global detections, last_memory_alert
    current_time = time.time()
    event_label = f"{label.title()} Detected"
    
    # Check if a detection with this label already exists in the feed
    existing_det = None
    for det in detections:
        if det["label"] == event_label:
            existing_det = det
            break
            
    if existing_det:
        # If detected recently (within 120s), update card in-place and bump to top
        if label in last_memory_alert and (current_time - last_memory_alert[label] < 120):
            existing_det["confidence"] = confidence
            existing_det["threat"] = threat
            existing_det["time"] = datetime.now().strftime("%H:%M:%S")
            existing_det["camera"] = camera_name
            
            # Bump to top
            detections.remove(existing_det)
            detections.insert(0, existing_det)
            last_memory_alert[label] = current_time
            return

    last_memory_alert[label] = current_time

    event = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "label": event_label,
        "confidence": confidence,
        "camera": camera_name,
        "location": "PM SHRI KV",
        "threat": threat
    }
    
    detections.insert(0, event)
    detections = detections[:MAX_DETECTIONS]

# ==========================================
# DRAW BOUNDING BOX
# ==========================================
def draw_box(frame, coords, confidence, color, label):
    x1, y1, x2, y2 = coords
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    
    text = f"{label.title()} {confidence:.1f}%"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.55
    thickness = 2
    
    # Get text size to draw a proper background rectangle
    (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    
    # Calculate background rectangle coordinates
    bg_y1 = max(0, y1 - text_height - 10)
    bg_y2 = y1 if bg_y1 > 0 else text_height + 10
    
    # Draw filled background
    cv2.rectangle(frame, (x1, bg_y1), (x1 + text_width + 10, bg_y2), color, -1)
    
    # Draw text
    text_y = y1 - 5 if bg_y1 > 0 else bg_y2 - 5
    cv2.putText(frame, text, (x1 + 5, text_y), font, font_scale, WHITE, thickness)

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
            current_time = time.time()
            
            try:
                # 1. Violence / Threat Detection (every 5 frames to save CPU)
                if state.frame_count_ai % 5 == 0:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    violence_prediction = violence_model.predict(image=rgb_frame)
                    state.last_violence_label = violence_prediction['label']
                    state.last_violence_confidence = violence_prediction['confidence']
                    
                    if state.last_violence_label in VIOLENCE_LABELS:
                        
                        # Use Face Recognition to identify attackers
                        recognized_faces = face_recognizer.recognize_faces(frame)
                        attacker_info = ""
                        if recognized_faces:
                            # Filter out duplicates and format
                            state.screenshot_count_this_event = 0
                        
                        state.last_violence_time = current_time
                        
                        # Only save max 2 screenshots per violence event, separated by at least 2 seconds
                        if state.screenshot_count_this_event < 2 and (current_time - state.last_screenshot_trigger_time > 2):
                            state.last_screenshot_trigger_time = current_time
                            try:
                                snapshot_dir = os.path.join(BASE_DIR, "snapshots")
                                os.makedirs(snapshot_dir, exist_ok=True)
                                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                                clean_cam_name = state.name.replace(" ", "_").replace("(", "").replace(")", "")
                                filename = f"violence_{clean_cam_name}_{timestamp}.jpg"
                                filepath = os.path.join(snapshot_dir, filename)
                                cv2.imwrite(filepath, frame)
                                
                                # Save to DB
                                from database import save_snapshot
                                save_snapshot(filepath)
                                global global_last_screenshot_time
                                global_last_screenshot_time = current_time
                                state.screenshot_count_this_event += 1
                                print(f"📸 Saved violence screenshot {state.screenshot_count_this_event}/2: {filepath}")
                            except Exception as e:
                                print(f"Error saving screenshot: {e}")
                        
                        if current_time - state.last_audio_alert_time > 10:
                            state.last_audio_alert_time = current_time
                                
                            def _speak_alert():
                                try:
                                    clean_name = state.name.replace(" (Live)", "")
                                    
                                    # Format the spoken text to sound more natural
                                    spoken_text = state.last_violence_label
                                    import platform
                                    if platform.system() == "Darwin":
                                        import subprocess
                                        subprocess.run(['say', f"Violence detected. [[slnc 600]] {spoken_text}"])
                                    else:
                                        engine = pyttsx3.init()
                                        engine.setProperty('rate', 160)
                                        engine.say(f"Violence detected. , , , {spoken_text}")
                                        engine.runAndWait()
                                except Exception as e:
                                    print("Audio alert error:", e)
                            threading.Thread(target=_speak_alert, daemon=True).start()

                # 2. YOLO Object Detection
                results = model.predict(source=frame, conf=0.85, imgsz=640, verbose=False)
                result = results[0]

                new_boxes = []
                current_person_count = 0
                
                # Run face recognition if there's any person
                has_person = any(model.names[int(box.cls[0])] == "person" for box in result.boxes)
                recognized_faces = []
                if has_person:
                    recognized_faces = face_recognizer.recognize_faces(frame)

                for box in result.boxes:
                    cls = int(box.cls[0])
                    class_name = model.names[cls]
                    confidence = round(float(box.conf[0]) * 100, 1)
                    coords = tuple(map(int, box.xyxy[0]))

                    if class_name == "person":
                        current_person_count += 1
                        
                        # Match face bounding box to person bounding box
                        matched_name = None
                        for face_data in recognized_faces:
                            fx1, fy1, fx2, fy2 = face_data['bbox']
                            x1, y1, x2, y2 = coords
                            cx = (fx1 + fx2) / 2
                            cy = (fy1 + fy2) / 2
                            # If face center is inside person bbox
                            if x1 <= cx <= x2 and y1 <= cy <= y2:
                                if face_data['name'] != "Unknown":
                                    matched_name = face_data['name']
                                break
                        
                        if matched_name:
                            class_name = matched_name
                            state.last_recognized_name = matched_name
                            state.last_recognized_time = current_time
                        else:
                            # Memory fallback: if a named person was recognized recently (within 10s) on this camera, keep their name
                            if state.last_recognized_name and (current_time - state.last_recognized_time < 10):
                                class_name = state.last_recognized_name

                        is_violent = (state.last_violence_label in VIOLENCE_LABELS)
                        threat, color = get_threat_level(current_person_count, is_violent)
                        new_boxes.append((coords, confidence, color, class_name))
                        
                        add_detection(class_name, confidence, threat, state.name)
                        if class_name != "person" and should_save_detection(class_name, state.name):
                            save_detection(label=class_name, confidence=confidence, severity=threat, camera=state.name)
                    else:
                        new_boxes.append((coords, confidence, GREEN, class_name))
                
                state.person_count = current_person_count
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
        is_violent = (state.last_violence_label in VIOLENCE_LABELS)
        threat, _ = get_threat_level(state.person_count, is_violent)
        
        if is_violent:
            cv2.putText(frame, f"CRITICAL: {state.last_violence_label.upper()}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, RED, 3)

        state.current_threat = threat

        # Global robot logic: update robot_dispatch dynamically based on all cameras
        any_critical = any(s.current_threat in ["HIGH", "CRITICAL"] for s in camera_states.values())
        global robot_dispatch, dispatch_camera
        robot_dispatch = any_critical
        if threat in ["HIGH", "CRITICAL"]:
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
        "people": total_people,
        "last_screenshot_time": global_last_screenshot_time
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
