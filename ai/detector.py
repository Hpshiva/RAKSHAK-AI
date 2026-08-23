import cv2
import os
import threading
import time
import pyttsx3
from collections import deque
from datetime import datetime
from database import save_detection
from ultralytics import YOLO
from ai.face_recognition import FaceRecognizer
from ai.model import Model

# ==========================================
# LOAD MODELS
# ==========================================

print("\n======================================")
print(" Loading Rakshak AI Unified Detector (YOLO + CLIP)...")
print("======================================")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUSTOM_MODEL_PATH = os.path.join(BASE_DIR, "runs", "detect", "rakshak_custom_model-6", "weights", "best.pt")

MODEL_PATH = os.environ.get("PERSON_MODEL_PATH", os.path.join(BASE_DIR, "models", "yolov8x.pt"))
if not os.path.isabs(MODEL_PATH):
    MODEL_PATH = os.path.join(BASE_DIR, MODEL_PATH)
if not os.path.isfile(MODEL_PATH):
    MODEL_PATH = os.path.join(BASE_DIR, "models", "yolov8x.pt")

SNAPSHOT_DIR = os.path.join(BASE_DIR, "snapshots_violence")
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

# 1. Base YOLO for Person and Knife
model = YOLO(MODEL_PATH)
YOLO_DEVICE = 0 if model.device.type == "cuda" else "cpu"
YOLO_HALF = YOLO_DEVICE != "cpu"

# 2. Custom YOLO for native Violence
custom_yolo = YOLO(CUSTOM_MODEL_PATH) if os.path.isfile(CUSTOM_MODEL_PATH) else None

PERSON_CONFIDENCE = 0.45
DETECTION_IMAGE_SIZE = 640
FACE_RECOGNITION_INTERVAL = 15
VIOLENCE_CHECK_SECONDS = 0.75

UPLOADED_PERSON_CONFIDENCE = 0.30
UPLOADED_DETECTION_IMAGE_SIZE = 640
UPLOADED_FACE_RECOGNITION_INTERVAL = 20
UPLOADED_VIOLENCE_CHECK_SECONDS = 0.45
WEAPON_GUN_CROP_THRESHOLD = 0.60
WEAPON_KNIFE_CROP_THRESHOLD = 0.60
VIOLENCE_SCORE_THRESHOLD = 0.65
VIOLENCE_INSTANT_THRESHOLD = 0.80
VIOLENCE_THREAT_HOLD_SECONDS = 4

MAX_SCREENSHOTS_PER_EVENT = 3
SCREENSHOT_CAPTURE_GAP_SECONDS = 2.5
HIGH_THREAT_PERSON_COUNT = int(os.environ.get("RAKSHAK_HIGH_THREAT_PERSON_COUNT", "6"))
CUSTOM_VIOLENCE_CONFIDENCE = 0.85 # Very high threshold to combat 1-epoch false positives

print(" YOLO Models Loaded Successfully")

print(" Loading Background Violence/Weapon Model (CLIP)...")
clip_model = Model()
print(" Background Model Loaded Successfully")

print(" Loading Face Recognition Model...")
face_recognizer = FaceRecognizer()
faces_dir = os.path.join(BASE_DIR, "faces")
os.makedirs(faces_dir, exist_ok=True)
face_recognizer.load_faces(faces_dir)

print("======================================\n")

# ==========================================
# GLOBALS & STATE
# ==========================================

ai_worker_lock = threading.Lock()
latest_frames_for_ai = {}
violence_worker_lock = threading.Lock()
latest_frames_for_violence = {}

detections = []
MAX_DETECTIONS = 15
last_event_times = {}

robot_dispatch = False
dispatch_camera = None
global_last_screenshot_time = 0
global_last_screenshot_filename = None

VIOLENCE_LABELS = {
    'fight on a street', 'street violence', 'violence in office', 'fire in office', 'fire on a street',
    'person holding a gun', 'person holding a knife', 'weapon', 'armed robbery',
    'physical assault', 'explosion', 'violence'
}

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
        self.cached_faces = []
        self.last_recognized_names = []
        self.last_violence_check_time = 0.0
        self.violence_history = deque(maxlen=3)
        self.previous_motion_frame = None
        self.motion_score = 0.0
        self.tracks = {}
        self.next_track_id = 1

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

GREEN = (0, 255, 0)
ORANGE = (0, 165, 255)
RED = (0, 0, 255)
WHITE = (255, 255, 255)
BLACK = (25, 25, 25)

def get_threat_level(count, is_violent=False):
    if is_violent:
        return "CRITICAL", RED
    if count >= HIGH_THREAT_PERSON_COUNT:
        return "HIGH", ORANGE
    return "LOW", GREEN

def is_violence_active(state, now=None):
    now = now if now is not None else time.time()
    active = (
        state.last_violence_label in VIOLENCE_LABELS
        and state.last_violence_time > 0
        and now - state.last_violence_time <= VIOLENCE_THREAT_HOLD_SECONDS
    )
    if not active and state.last_violence_label in VIOLENCE_LABELS:
        state.last_violence_label = "Unknown"
        state.last_violence_confidence = 0.0
        state.screenshot_count_this_event = 0
    return active

def add_detection(label, confidence, threat, camera_name):
    global detections
    now = time.time()
    event_key = (label.lower(), threat, camera_name)
    if now - last_event_times.get(event_key, 0) < 5:
        return
    last_event_times[event_key] = now
    event = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "label": f"{label.title()} Detected",
        "confidence": confidence,
        "camera": camera_name,
        "location": "PM SHRI KV",
        "threat": threat
    }
    detections.insert(0, event)
    detections = detections[:MAX_DETECTIONS]

def draw_box(frame, coords, confidence, color, label):
    x1, y1, x2, y2 = coords
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    text = f"{label.title()} {confidence:.1f}%"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.55
    thickness = 2
    (text_width, text_height), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    bg_y1 = max(0, y1 - text_height - 10)
    bg_y2 = y1 if bg_y1 > 0 else text_height + 10
    cv2.rectangle(frame, (x1, bg_y1), (x1 + text_width + 10, bg_y2), color, -1)
    text_y = y1 - 5 if bg_y1 > 0 else bg_y2 - 5
    cv2.putText(frame, text, (x1 + 5, text_y), font, font_scale, WHITE, thickness)

def _stabilize_person_box(state, coords, claimed_track_ids):
    def iou(first, second):
        ax1, ay1, ax2, ay2 = first
        bx1, by1, bx2, by2 = second
        intersection = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(0, min(ay2, by2) - max(ay1, by1))
        union = max(1, (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection)
        return intersection / union

    best_id, best_iou = None, 0.0
    for track_id, track in state.tracks.items():
        if track_id in claimed_track_ids:
            continue
        overlap = iou(track["coords"], coords)
        if overlap > best_iou:
            best_id, best_iou = track_id, overlap
    if best_id is None or best_iou < 0.30:
        best_id = state.next_track_id
        state.next_track_id += 1
        smoothed = coords
    else:
        previous = state.tracks[best_id]["coords"]
        smoothed = tuple(int(old * 0.55 + new * 0.45) for old, new in zip(previous, coords))
    claimed_track_ids.add(best_id)
    state.tracks[best_id] = {"coords": smoothed, "seen": state.frame_count_ai}
    state.tracks = {
        track_id: track for track_id, track in state.tracks.items()
        if state.frame_count_ai - track["seen"] <= 12
    }
    return smoothed

def _format_names_for_speech(names):
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{names[0]}, {names[1]}, and others"

def _build_voice_alert_message(state):
    label = (state.last_violence_label or "violence").replace("_", " ").strip()
    message = f"Alert. {label.capitalize()} detected"
    names = _format_names_for_speech(state.last_recognized_names)
    if names:
        message += f", involving {names}"
    return message + "."

screenshot_lock = threading.Lock()

def _trigger_threat_actions(state, frame, current_time):
    with screenshot_lock:
        should_capture = (
            state.screenshot_count_this_event < MAX_SCREENSHOTS_PER_EVENT
            and current_time - state.last_screenshot_trigger_time >= SCREENSHOT_CAPTURE_GAP_SECONDS
        )
        if should_capture:
            try:
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
                clean_name = state.name.replace(" ", "_").replace("(", "").replace(")", "")
                filename = f"violence_{clean_name}_{timestamp}.jpg"
                filepath = os.path.join(SNAPSHOT_DIR, filename)
                if not cv2.imwrite(filepath, frame):
                    raise OSError(f"Could not write screenshot to {filepath}")
                from database import save_snapshot
                save_snapshot(
                    filepath,
                    camera=state.name,
                    incident_label=state.last_violence_label,
                    student_names=state.last_recognized_names,
                )
                global global_last_screenshot_time, global_last_screenshot_filename
                global_last_screenshot_time = current_time
                global_last_screenshot_filename = filename
                state.screenshot_count_this_event += 1
                state.last_screenshot_trigger_time = current_time
            except Exception as error:
                print(f"Error saving screenshot: {error}")

    # ZERO-DELAY ALERT with 3-second cooldown to prevent overlapping TTS
    if current_time - state.last_audio_alert_time > 3:
        state.last_audio_alert_time = current_time
        message = _build_voice_alert_message(state)

        def _speak_alert():
            try:
                engine = pyttsx3.init()
                engine.setProperty("rate", 160)
                engine.say(message)
                engine.runAndWait()
            except Exception as error:
                print("Audio alert error:", error)

        threading.Thread(target=_speak_alert, daemon=True).start()

# ==========================================
# CLIP VIOLENCE WORKER (Guns, Knives, Complex Actions)
# ==========================================
def _classify_violence_frame(frame, state):
    motion_frame = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90))
    if state.previous_motion_frame is not None:
        state.motion_score = float(
            cv2.mean(cv2.absdiff(motion_frame, state.previous_motion_frame))[0]
        )
    state.previous_motion_frame = motion_frame
    rgb_images = [cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)]
    height, width = frame.shape[:2]
    priority_boxes = sorted(
        state.cached_boxes,
        key=lambda item: (item[0][2] - item[0][0]) * (item[0][3] - item[0][1]),
        reverse=True,
    )[:2]
    for coords, _, _, _ in priority_boxes:
        x1, y1, x2, y2 = coords
        pad_x = max(24, int((x2 - x1) * 0.20))
        pad_y = max(24, int((y2 - y1) * 0.15))
        crop = frame[
            max(0, y1 - pad_y):min(height, y2 + pad_y),
            max(0, x1 - pad_x):min(width, x2 + pad_x),
        ]
        if crop.size:
            rgb_images.append(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))

    score_sets = clip_model.predict_batch_scores(rgb_images)
    full_scores = score_sets[0]
    threat_label = max(VIOLENCE_LABELS, key=lambda label: full_scores.get(label, -1.0))
    threat_score = full_scores.get(threat_label, 0.0)
    normal_score = max(
        (score for label, score in full_scores.items() if label not in VIOLENCE_LABELS),
        default=0.0,
    )
    candidate = (
        {"label": threat_label, "confidence": threat_score}
        if threat_score >= VIOLENCE_SCORE_THRESHOLD and threat_score >= normal_score
        else {"label": "Unknown", "confidence": threat_score}
    )

    for crop_scores in score_sets[1:]:
        crop_normal = max(
            (score for label, score in crop_scores.items() if label not in VIOLENCE_LABELS),
            default=0.0,
        )
        gun_score = crop_scores.get("person holding a gun", 0.0)
        knife_score = crop_scores.get("person holding a knife", 0.0)
        if knife_score >= WEAPON_KNIFE_CROP_THRESHOLD and knife_score >= gun_score and knife_score >= crop_normal + 0.003:
            return {"label": "person holding a knife", "confidence": knife_score}
        if gun_score >= WEAPON_GUN_CROP_THRESHOLD and gun_score >= crop_normal + 0.003:
            return {"label": "person holding a gun", "confidence": gun_score}
    return candidate

def violence_worker():
    while True:
        with violence_worker_lock:
            frames = list(latest_frames_for_violence.items())
            latest_frames_for_violence.clear()
        if not frames:
            time.sleep(0.01)
            continue
        frames.sort(key=lambda item: not str(item[0]).startswith("upload_"))
        for cid, frame in frames:
            state = get_camera_state(cid)
            try:
                prediction = _classify_violence_frame(frame, state)
                current_time = time.time()
                state.violence_history.append(prediction)
                recent_hits = [
                    item for item in state.violence_history
                    if item["label"] in VIOLENCE_LABELS
                ]
                confirmed = (
                    prediction["label"] in {"person holding a gun", "person holding a knife"}
                    or prediction["confidence"] >= VIOLENCE_INSTANT_THRESHOLD
                    or len(recent_hits) >= 2
                )
                if prediction["label"] in VIOLENCE_LABELS and confirmed:
                    matching_scores = [
                        item["confidence"] for item in recent_hits
                        if item["label"] == prediction["label"]
                    ]
                    state.last_violence_label = prediction["label"]
                    state.last_violence_confidence = sum(matching_scores) / len(matching_scores)
                    state.last_violence_time = current_time
                    _trigger_threat_actions(state, frame, current_time)
                elif not recent_hits and not is_violence_active(state, current_time):
                    state.screenshot_count_this_event = 0
            except Exception as error:
                print(f"Violence Worker Error on cam {cid}:", error)

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

        frames_to_process.sort(key=lambda item: not str(item[0]).startswith("upload_"))
            
        if not frames_to_process:
            time.sleep(0.01)
            continue
            
        for cid, frame in frames_to_process:
            try:
                state = get_camera_state(cid)
                state.frame_count_ai += 1
                current_time = time.time()
                is_uploaded_video = str(cid).startswith("upload_")
                face_interval = (
                    UPLOADED_FACE_RECOGNITION_INTERVAL
                    if is_uploaded_video else FACE_RECOGNITION_INTERVAL
                )
                person_confidence = (
                    UPLOADED_PERSON_CONFIDENCE
                    if is_uploaded_video else PERSON_CONFIDENCE
                )
                detection_image_size = (
                    UPLOADED_DETECTION_IMAGE_SIZE
                    if is_uploaded_video else DETECTION_IMAGE_SIZE
                )

                # 1. Base YOLO for Person and Knife
                results = model.predict(
                    source=frame,
                    classes=[0, 43], # Person, Knife
                    conf=person_confidence,
                    iou=0.45,
                    imgsz=detection_image_size,
                    max_det=30,
                    device=YOLO_DEVICE,
                    half=YOLO_HALF,
                    verbose=False,
                )
                
                # 2. Custom YOLO for Violence
                custom_results = None
                if custom_yolo:
                    custom_results = custom_yolo.predict(
                        source=frame,
                        classes=[1], # Violence
                        conf=CUSTOM_VIOLENCE_CONFIDENCE,
                        iou=0.45,
                        imgsz=detection_image_size,
                        max_det=30,
                        device=YOLO_DEVICE,
                        half=YOLO_HALF,
                        verbose=False,
                    )

                new_boxes = []
                current_person_count = 0
                violence_detected_this_frame = False
                
                has_person = len(results[0].boxes) > 0
                if has_person and (
                    not state.cached_faces
                    or state.frame_count_ai % face_interval == 0
                ):
                    state.cached_faces = face_recognizer.recognize_faces(frame)
                elif not has_person:
                    state.cached_faces = []
                recognized_faces = state.cached_faces
                state.last_recognized_names = list(dict.fromkeys(
                    face["name"] for face in recognized_faces
                    if face.get("name") and face["name"] != "Unknown"
                ))

                frame_event = None
                claimed_track_ids = set()
                
                # Process Custom YOLO Violence (Zero-Delay)
                if custom_results:
                    for box in custom_results[0].boxes:
                        class_name = "violence"
                        confidence = round(float(box.conf[0]) * 100, 1)
                        coords = tuple(map(int, box.xyxy[0]))
                        
                        violence_detected_this_frame = True
                        state.last_violence_time = current_time
                        state.last_violence_label = class_name
                        state.last_violence_confidence = confidence
                        _trigger_threat_actions(state, frame, current_time)
                        
                        new_boxes.append((coords, confidence, RED, class_name))
                        if frame_event is None:
                            frame_event = (class_name, confidence, "CRITICAL")
                
                # Process Base YOLO (Person, Knife)
                for box in results[0].boxes:
                    cls = int(box.cls[0])
                    class_name = model.names[cls].lower()
                    confidence = round(float(box.conf[0]) * 100, 1)
                    coords = tuple(map(int, box.xyxy[0]))

                    if class_name == "person":
                        coords = _stabilize_person_box(state, coords, claimed_track_ids)
                        current_person_count += 1
                        
                        for face_data in recognized_faces:
                            fx1, fy1, fx2, fy2 = face_data['bbox']
                            x1, y1, x2, y2 = coords
                            cx = (fx1 + fx2) / 2
                            cy = (fy1 + fy2) / 2
                            if x1 <= cx <= x2 and y1 <= cy <= y2:
                                if face_data['name'] != "Unknown":
                                    class_name = face_data['name']
                                break
                    
                    if class_name == "knife":
                        violence_detected_this_frame = True
                        state.last_violence_time = current_time
                        state.last_violence_label = class_name
                        state.last_violence_confidence = confidence
                        _trigger_threat_actions(state, frame, current_time)

                    is_violent = is_violence_active(state, current_time)
                    
                    if class_name in ["knife"]:
                        color = RED
                        threat = "CRITICAL"
                    else:
                        threat, color = get_threat_level(current_person_count, is_violent)
                    
                    new_boxes.append((coords, confidence, color, class_name))
                    if frame_event is None or threat == "CRITICAL":
                        frame_event = (class_name, confidence, threat)

                if not violence_detected_this_frame and not is_violence_active(state, current_time):
                    state.screenshot_count_this_event = 0

                state.person_count = current_person_count
                state.cached_boxes = new_boxes
                if frame_event:
                    event_label, event_confidence, threat = frame_event
                    add_detection(event_label, event_confidence, threat, state.name)
                    if threat == "CRITICAL":
                        save_detection(
                            label=event_label,
                            confidence=event_confidence,
                            severity=threat,
                            camera=state.name,
                        )
            except Exception as e:
                print(f"AI Worker Error on cam {cid}:", e)

worker_thread = threading.Thread(target=ai_worker, daemon=True)
worker_thread.start()
violence_thread = threading.Thread(target=violence_worker, daemon=True)
violence_thread.start()

# ==========================================
# MAIN DETECTION FUNCTION (INSTANT)
# ==========================================
def detect(frame, camera_id="0", camera_name="Main Gate"):
    if str(camera_id) == "0":
        frame = cv2.flip(frame, 1)

    global robot_dispatch, dispatch_camera

    state = get_camera_state(camera_id, camera_name)
    state.frame_count += 1

    try:
        with ai_worker_lock:
            latest_frames_for_ai[camera_id] = frame.copy()

        # Queue for background CLIP model for guns/complex violence
        now = time.time()
        violence_interval = (
            UPLOADED_VIOLENCE_CHECK_SECONDS
            if str(camera_id).startswith("upload_") else VIOLENCE_CHECK_SECONDS
        )
        if now - state.last_violence_check_time >= violence_interval:
            state.last_violence_check_time = now
            with violence_worker_lock:
                latest_frames_for_violence[camera_id] = frame.copy()

        for coords, confidence, color, class_name in state.cached_boxes:
            draw_box(frame, coords, confidence, color, class_name)

        is_violent = is_violence_active(state)
        threat, _ = get_threat_level(state.person_count, is_violent)
        
        if is_violent:
            cv2.putText(frame, f"CRITICAL: {state.last_violence_label.upper()}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, RED, 3)

        state.current_threat = threat

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
    global robot_dispatch, dispatch_camera
    now = time.time()
    for state in camera_states.values():
        state.current_threat, _ = get_threat_level(
            state.person_count,
            is_violence_active(state, now),
        )

    critical_states = [
        state for state in camera_states.values()
        if state.current_threat in ["HIGH", "CRITICAL"]
    ]
    robot_dispatch = bool(critical_states)
    if not robot_dispatch:
        dispatch_camera = None

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
        "last_screenshot_time": global_last_screenshot_time,
        "last_screenshot_filename": global_last_screenshot_filename
    }

# ==========================================
# RESET DETECTIONS
# ==========================================
def clear_detections():
    global robot_dispatch, dispatch_camera
    detections.clear()
    last_event_times.clear()
    robot_dispatch = False
    dispatch_camera = None
    for s in camera_states.values():
        s.person_count = 0
        s.current_threat = "LOW"
