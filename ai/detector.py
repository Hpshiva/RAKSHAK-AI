import cv2
import os
import threading
import time
import pyttsx3
from datetime import datetime
from database import save_detection, should_save_detection
from ultralytics import YOLO, YOLOE
from ai.face_recognition import FaceRecognizer

# ==========================================
# LOAD YOLO MODEL
# ==========================================

print("\n======================================")
print(" Loading Rakshak AI Detector...")
print("======================================")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YOLO_CONFIDENCE = float(os.environ.get("YOLO_CONFIDENCE", "0.45"))
YOLO_IMAGE_SIZE = int(os.environ.get("YOLO_IMAGE_SIZE", "480"))
VIOLENCE_CHECK_INTERVAL = int(os.environ.get("VIOLENCE_CHECK_INTERVAL", "30"))
FACE_CHECK_INTERVAL = int(os.environ.get("FACE_CHECK_INTERVAL", "3"))
THREAT_CHECK_INTERVAL = int(os.environ.get("THREAT_CHECK_INTERVAL", "4"))
THREAT_CONFIDENCE = float(os.environ.get("THREAT_CONFIDENCE", "0.15"))
THREAT_IMAGE_SIZE = int(os.environ.get("THREAT_IMAGE_SIZE", "480"))
MODEL_PATH = os.environ.get(
    "YOLO_MODEL_PATH",
    os.path.join(BASE_DIR, "models", "yolo26s.pt"),
)
model = YOLO(MODEL_PATH)

print(f" YOLO Model Loaded Successfully: {os.path.basename(MODEL_PATH)}")
print(
    f" Detection tuning: conf={YOLO_CONFIDENCE:.2f}, imgsz={YOLO_IMAGE_SIZE}, "
    f"violence_every={VIOLENCE_CHECK_INTERVAL}, face_every={FACE_CHECK_INTERVAL}"
)

THREAT_CLASSES = [
    "knife", "handgun", "pistol", "firearm", "syringe",
]
THREAT_LABELS = {
    "handgun": "gun",
    "pistol": "gun",
    "firearm": "gun",
}
threat_model = None
try:
    threat_model_path = os.path.join(BASE_DIR, "models", "yoloe-26s-seg.pt")
    models_dir = os.path.dirname(threat_model_path)
    previous_directory = os.getcwd()
    os.chdir(models_dir)
    try:
        threat_model = YOLOE(threat_model_path)
        threat_model.set_classes(THREAT_CLASSES)
    finally:
        os.chdir(previous_directory)
    print(" Threat Model Loaded Successfully: YOLOE-26s open vocabulary")
except Exception as error:
    print(f" Threat model unavailable; continuing with standard YOLO: {error}")

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
        self.cached_faces = []
        self.cached_threat_boxes = []
        self.last_prohibited_item_time = 0

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

    # The in-memory feed and database audit must be written from the same
    # proven event path. This prevents alerts from appearing on the dashboard
    # while the audit history remains empty.
    try:
        if should_save_detection(label, camera_name):
            save_detection(
                label=label,
                confidence=confidence,
                severity=threat,
                camera=camera_name,
            )
    except Exception as error:
        print(f"Failed to persist detection '{label}' from {camera_name}: {error}")

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
                # ViT-L takes ~2.2s on this CPU, so run it periodically instead
                # of blocking almost every YOLO update.
                if state.frame_count_ai % VIOLENCE_CHECK_INTERVAL == 0:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    violence_prediction = violence_model.predict(image=rgb_frame)
                    state.last_violence_label = violence_prediction['label']
                    state.last_violence_confidence = violence_prediction['confidence']
                    
                    if state.last_violence_label in VIOLENCE_LABELS:
                        # A quiet period marks a new incident and allows a fresh
                        # pair of evidence screenshots to be captured.
                        if current_time - state.last_violence_time > 10:
                            state.screenshot_count_this_event = 0
                        state.last_violence_time = current_time

                        if should_save_detection(state.last_violence_label, state.name):
                            save_detection(
                                label=state.last_violence_label,
                                confidence=round(state.last_violence_confidence * 100, 1),
                                severity="CRITICAL",
                                camera=state.name,
                            )
                        
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
                                
                            camera_name = state.name
                            violence_label = state.last_violence_label

                            def _speak_alert(name=camera_name, label=violence_label):
                                try:
                                    # Format the spoken text to sound more natural
                                    spoken_text = label
                                    import platform
                                    if platform.system() == "Darwin":
                                        import subprocess
                                        subprocess.run(
                                            ['say', f"Violence detected at {name}. [[slnc 600]] {spoken_text}"],
                                            check=False,
                                        )
                                    else:
                                        engine = pyttsx3.init()
                                        engine.setProperty('rate', 160)
                                        engine.say(f"Violence detected at {name}. {spoken_text}")
                                        engine.runAndWait()
                                except Exception as e:
                                    print("Audio alert error:", e)
                            threading.Thread(target=_speak_alert, daemon=True).start()

                # 2. Open-vocabulary prohibited-item detection. Results are
                # cached so red threat boxes remain visible between checks.
                if threat_model is not None and state.frame_count_ai % THREAT_CHECK_INTERVAL == 0:
                    threat_results = threat_model.predict(
                        source=frame,
                        conf=THREAT_CONFIDENCE,
                        imgsz=THREAT_IMAGE_SIZE,
                        verbose=False,
                        agnostic_nms=True,
                    )[0]
                    detected_threats = []
                    for threat_box in threat_results.boxes:
                        threat_class = int(threat_box.cls[0])
                        raw_label = threat_model.names[threat_class]
                        threat_label = THREAT_LABELS.get(raw_label, raw_label)
                        threat_confidence = round(float(threat_box.conf[0]) * 100, 1)
                        threat_coords = tuple(map(int, threat_box.xyxy[0]))
                        detected_threats.append(
                            (threat_coords, threat_confidence, RED, threat_label)
                        )
                        add_detection(threat_label, threat_confidence, "CRITICAL", state.name)
                    state.cached_threat_boxes = detected_threats
                    if detected_threats:
                        state.last_prohibited_item_time = current_time

                # 3. Standard fast YOLO object detection
                results = model.predict(
                    source=frame,
                    conf=YOLO_CONFIDENCE,
                    imgsz=YOLO_IMAGE_SIZE,
                    verbose=False,
                )
                result = results[0]

                new_boxes = list(state.cached_threat_boxes)
                current_person_count = 0
                
                # Run face recognition if there's any person
                has_person = any(model.names[int(box.cls[0])] == "person" for box in result.boxes)
                if has_person and state.frame_count_ai % FACE_CHECK_INTERVAL == 0:
                    state.cached_faces = face_recognizer.recognize_faces(frame)
                recognized_faces = state.cached_faces if has_person else []

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
                    else:
                        object_threat = "HIGH" if class_name in {"knife", "gun", "syringe"} else "LOW"
                        object_color = ORANGE if object_threat == "HIGH" else GREEN
                        new_boxes.append((coords, confidence, object_color, class_name))
                        add_detection(class_name, confidence, object_threat, state.name)
                
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
        prohibited_item_active = time.time() - state.last_prohibited_item_time < 5
        threat, _ = get_threat_level(
            state.person_count,
            is_violent or prohibited_item_active,
        )
        
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
