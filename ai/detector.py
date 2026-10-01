import cv2
import os
import threading
import time
import numpy as np
import torch
import pyttsx3
from collections import deque
from datetime import datetime
from database import save_detection
from ultralytics import YOLO
from ai.face_recognition import FaceRecognizer
from ai.model import Model
from ai.linear_probe import ProbeClassifier
from ai.height_estimator import height_estimator

# ==========================================
# LOAD MODELS
# ==========================================

print("\n======================================")
print(" Loading Rakshak AI Unified Detector (YOLO + CLIP)...")
print("======================================")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUSTOM_MODEL_CANDIDATES = [
    os.path.join(BASE_DIR, "models", "violence_yolov8.pt"),
    os.path.join(BASE_DIR, "runs", "detect", "rakshak_custom_model", "weights", "best.pt"),
    os.path.join(BASE_DIR, "runs", "detect", "rakshak_custom_model-6", "weights", "best.pt"),
]
CUSTOM_MODEL_PATH = next((p for p in CUSTOM_MODEL_CANDIDATES if os.path.isfile(p)), None)

MODEL_PATH = os.environ.get("PERSON_MODEL_PATH", os.path.join(BASE_DIR, "models", "yolov8x.pt"))
if not os.path.isabs(MODEL_PATH):
    MODEL_PATH = os.path.join(BASE_DIR, MODEL_PATH)
if not os.path.isfile(MODEL_PATH):
    MODEL_PATH = os.path.join(BASE_DIR, "yolov8n.pt") if os.path.isfile(os.path.join(BASE_DIR, "yolov8n.pt")) else os.path.join(BASE_DIR, "models", "yolov8x.pt")

SNAPSHOT_DIR = os.path.join(BASE_DIR, "snapshots_violence")
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

# 1. Base YOLO for Person and Knife (Auto-detect CUDA -> Apple Silicon MPS -> CPU)
model = YOLO(MODEL_PATH)
if torch.cuda.is_available():
    YOLO_DEVICE = 0
    YOLO_HALF = True
elif torch.backends.mps.is_available():
    YOLO_DEVICE = "mps"
    YOLO_HALF = False
else:
    YOLO_DEVICE = "cpu"
    YOLO_HALF = False

# 2. Custom YOLO for native Violence
custom_yolo = YOLO(CUSTOM_MODEL_PATH) if CUSTOM_MODEL_PATH and os.path.isfile(CUSTOM_MODEL_PATH) else None

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
VIOLENCE_THREAT_HOLD_SECONDS = 3.5

MAX_SCREENSHOTS_PER_EVENT = 3
SCREENSHOT_CAPTURE_GAP_SECONDS = 2.5
HIGH_THREAT_PERSON_COUNT = int(os.environ.get("RAKSHAK_HIGH_THREAT_PERSON_COUNT", "6"))
CUSTOM_VIOLENCE_CONFIDENCE = 0.65 # Calibrated high-confidence threshold to prevent false alarms
AUDIO_ALERT_COOLDOWN_SECONDS = 20.0
DETECTION_SAVE_COOLDOWN_SECONDS = 15.0
VIOLENCE_CONSECUTIVE_FRAMES_REQUIRED = 3

print(" YOLO Models Loaded Successfully")

print(" Loading Background Violence/Weapon Model (CLIP)...")
clip_model = Model()
print(" Background Model Loaded Successfully")

PROBE_PATH = os.path.join(BASE_DIR, "models", "clip_probe.pt")
probe_classifier = ProbeClassifier(PROBE_PATH) if os.path.isfile(PROBE_PATH) else None
if probe_classifier and probe_classifier.is_trained:
    print(" Loaded Fine-Tuned Linear Probe Classifier")

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

def detect_camera_tampering(frame):
    """
    Physical Camera Tampering & Blinding Detection (LIMITATIONS.md Section 5.1).
    Detects:
    1. Lens obstruction / Covered lens (spray paint, cloth, completely black or uniform flat surface)
    2. Sensor blinding / Direct glare (high-intensity laser or bright flashlight saturating sensor)
    3. Severe defocus / blurring (Vaseline, lens smudge, extreme optical blur)
    Returns: (is_tampered: bool, tamper_type: str, confidence: float)
    """
    if frame is None or frame.size == 0:
        return False, "", 0.0

    try:
        small = cv2.resize(frame, (160, 120))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

        mean_val = float(np.mean(gray))
        std_val = float(np.std(gray))

        # 1. Lens Obstruction (covered, painted, completely blocked)
        if mean_val < 18.0 and std_val < 10.0:
            return True, "Lens Obstructed (Covered / Blackout)", 96.0
        if std_val < 4.0:
            return True, "Lens Obstructed (Uniform Surface)", 92.0

        # 2. Sensor Blinding / Direct Glare / Laser
        saturated_ratio = float(np.count_nonzero(gray > 245)) / float(gray.size)
        if saturated_ratio > 0.55 and mean_val > 215.0:
            return True, "Sensor Blinded (High Glare / Laser)", 95.0

        # 3. Severe Defocus / Vaseline Smudge
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if lap_var < 5.0 and std_val < 15.0:
            return True, "Camera Defocused / Smudged Lens", 88.0

        return False, "", 0.0
    except Exception:
        return False, "", 0.0


class CameraState:
    def __init__(self, name):
        self.name = name
        self.person_count = 0
        self.frame_count = 0
        self.frame_count_ai = 0
        self.last_violence_label = "Unknown"
        self.last_violence_confidence = 0.0
        self.peak_threat_confidence = 0.0
        self.current_threat = "LOW"
        self.cached_boxes = []
        self.last_audio_alert_time = 0
        self.screenshot_count_this_event = 0
        self.last_violence_time = 0
        self.last_screenshot_trigger_time = 0
        self.cached_faces = []
        self.last_recognized_names = []
        self.last_violence_check_time = 0.0
        self.violence_history = deque(maxlen=8)
        self.violence_score_ewma = 0.0
        self.alpha_ewma = 0.45
        self.previous_motion_frame = None
        self.motion_score = 0.0
        self.tracks = {}
        self.next_track_id = 1
        self.last_estimated_heights = []
        self.consecutive_violence_hits = 0
        self.last_db_save_time = 0.0
        # Physical camera tampering state
        self.is_tampered = False
        self.tamper_type = ""
        self.last_tamper_alert_time = 0.0
        # Geofenced & zone sensitivity profile (LIMITATIONS.md Section 8 Phase 1.2)
        name_lower = name.lower()
        if any(term in name_lower for term in ["gym", "ground", "sports", "play", "court"]):
            self.zone_profile = "sports_relaxed"
        elif any(term in name_lower for term in ["corridor", "hall", "office", "vault", "gate", "entrance"]):
            self.zone_profile = "high_security"
        else:
            self.zone_profile = "standard"

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
        state.peak_threat_confidence = 0.0
        state.screenshot_count_this_event = 0
        state.consecutive_violence_hits = 0
    return active

def add_detection(label, confidence, threat, camera_name):
    global detections
    now = time.time()
    event_key = (label.lower(), threat, camera_name)
    if now - last_event_times.get(event_key, 0) < 10.0:
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
    return smoothed, best_id

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
                    person_heights=state.last_estimated_heights,
                )
                global global_last_screenshot_time, global_last_screenshot_filename
                global_last_screenshot_time = current_time
                global_last_screenshot_filename = filename
                state.screenshot_count_this_event += 1
                state.last_screenshot_trigger_time = current_time
            except Exception as error:
                print(f"Error saving screenshot: {error}")

    # Rate-limited voice alert to prevent spamming TTS
    if current_time - state.last_audio_alert_time >= AUDIO_ALERT_COOLDOWN_SECONDS:
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
# PROXIMITY & MULTI-SCALE CROP UTILITIES
# ==========================================
def _check_person_proximity(cached_boxes):
    """
    Returns True if at least two people are close to each other
    or their bounding boxes have substantial spatial overlap.
    """
    person_boxes = [coords for coords, _, _, label in cached_boxes if label == "person" or "person" in label]
    if len(person_boxes) < 2:
        return False
    for i in range(len(person_boxes)):
        x1_a, y1_a, x2_a, y2_a = person_boxes[i]
        w_a = x2_a - x1_a
        cx_a, cy_a = (x1_a + x2_a) / 2, (y1_a + y2_a) / 2
        for j in range(i + 1, len(person_boxes)):
            x1_b, y1_b, x2_b, y2_b = person_boxes[j]
            w_b = x2_b - x1_b
            cx_b, cy_b = (x1_b + x2_b) / 2, (y1_b + y2_b) / 2
            
            avg_w = max(1, (w_a + w_b) / 2.0)
            dist_x = abs(cx_a - cx_b)
            dist_y = abs(cy_a - cy_b)
            
            if dist_x < avg_w * 1.6 and dist_y < avg_w * 2.5:
                return True
    return False

def _enhance_crop(crop_bgr):
    """Applies Contrast Limited Adaptive Histogram Equalization (CLAHE) to boost shadows and details."""
    if crop_bgr is None or crop_bgr.size == 0:
        return crop_bgr
    try:
        lab = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2LAB)
        l_chan, a_chan, b_chan = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l_chan)
        merged = cv2.merge((cl, a_chan, b_chan))
        return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
    except Exception:
        return crop_bgr

def _compute_bayesian_confidence(scores: list[float], max_ceiling: float = 99.4) -> float:
    """
    Computes Bayesian probability compounding across multiple confirming detections:
        P_fused = 1 - product(1 - p_i)
    Elevates sustained multi-frame detections to 98.0% - 99.4% mathematically.
    """
    if not scores:
        return 0.0
    
    normalized_probs = []
    for s in scores:
        p = s / 100.0 if s > 1.0 else s
        p = max(0.15, min(0.96, p))
        normalized_probs.append(p)
        
    prod_complement = 1.0
    for p in normalized_probs:
        prod_complement *= (1.0 - p)
        
    fused_p = 1.0 - prod_complement
    return round(min(max_ceiling, max(float(scores[-1]), fused_p * 100.0)), 1)

def _extract_priority_crops(frame, cached_boxes):
    """
    Extracts full person crops plus focused upper-torso and hand/hip quadrant crops
    with adaptive CLAHE contrast enhancement for sharp weapon details.
    """
    height, width = frame.shape[:2]
    crops = []
    priority_boxes = sorted(
        cached_boxes,
        key=lambda item: (item[0][2] - item[0][0]) * (item[0][3] - item[0][1]),
        reverse=True,
    )[:2]
    
    for coords, _, _, _ in priority_boxes:
        x1, y1, x2, y2 = coords
        bw = x2 - x1
        bh = y2 - y1
        pad_x = max(24, int(bw * 0.20))
        pad_y = max(24, int(bh * 0.15))
        
        # 1. Full person crop with padding
        crop_full = frame[
            max(0, y1 - pad_y):min(height, y2 + pad_y),
            max(0, x1 - pad_x):min(width, x2 + pad_x),
        ]
        if crop_full.size > 0:
            enhanced_full = _enhance_crop(crop_full)
            crops.append(cv2.cvtColor(enhanced_full, cv2.COLOR_BGR2RGB))
            
        # 2. Upper/mid-torso crop (hands raised, pointing weapons)
        crop_upper = frame[
            max(0, y1):min(height, int(y1 + bh * 0.70)),
            max(0, x1):min(width, x2),
        ]
        if crop_upper.size > 0:
            enhanced_upper = _enhance_crop(crop_upper)
            crops.append(cv2.cvtColor(enhanced_upper, cv2.COLOR_BGR2RGB))
            
        # 3. Mid/lower-torso crop (hands at sides, pockets, waistline)
        crop_lower = frame[
            max(0, int(y1 + bh * 0.35)):min(height, y2),
            max(0, x1):min(width, x2),
        ]
        if crop_lower.size > 0:
            enhanced_lower = _enhance_crop(crop_lower)
            crops.append(cv2.cvtColor(enhanced_lower, cv2.COLOR_BGR2RGB))
            
    return crops

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
    crops = _extract_priority_crops(frame, state.cached_boxes)
    rgb_images.extend(crops)

    score_sets = clip_model.predict_batch_scores(rgb_images)
    full_scores = score_sets[0]
    threat_label = max(VIOLENCE_LABELS, key=lambda label: full_scores.get(label, -1.0))
    threat_score = full_scores.get(threat_label, 0.0)
    normal_score = max(
        (score for label, score in full_scores.items() if label not in VIOLENCE_LABELS),
        default=0.0,
    )
    
    # Proximity gating: Physical fights require multiple people in proximity
    is_physical_fight = threat_label in {"fight on a street", "street violence", "physical assault", "violence in office"}
    has_proximity = _check_person_proximity(state.cached_boxes)
    
    # Suppress physical fight classification if only 1 person or people are far apart
    if is_physical_fight and not has_proximity:
        threat_score = threat_score * 0.75

    # Motion gating: stationary scenes without movement shouldn't trigger high-energy fight alerts
    if is_physical_fight and state.motion_score < 1.0:
        threat_score = threat_score * 0.80

    candidate = (
        {"label": threat_label, "confidence": threat_score}
        if threat_score >= VIOLENCE_SCORE_THRESHOLD and threat_score >= normal_score
        else {"label": "Unknown", "confidence": threat_score}
    )

    # Check weapon crops against benign negative contrast objects
    for crop_scores in score_sets[1:]:
        crop_normal = max(
            (score for label, score in crop_scores.items() if label not in VIOLENCE_LABELS),
            default=0.0,
        )
        gun_score = crop_scores.get("person holding a gun", 0.0)
        knife_score = crop_scores.get("person holding a knife", 0.0)
        phone_score = crop_scores.get("person holding a mobile phone", 0.0)
        umbrella_score = crop_scores.get("person holding an umbrella or stick", 0.0)
        bottle_score = crop_scores.get("person holding a water bottle", 0.0)
        
        # Disambiguate guns from phones/bottles
        gun_benign_max = max(phone_score, bottle_score, crop_normal)
        if gun_score >= WEAPON_GUN_CROP_THRESHOLD and gun_score >= gun_benign_max + 0.005:
            return {"label": "person holding a gun", "confidence": gun_score}
            
        # Disambiguate knives from umbrellas/pens
        knife_benign_max = max(umbrella_score, phone_score, crop_normal)
        if knife_score >= WEAPON_KNIFE_CROP_THRESHOLD and knife_score >= knife_benign_max + 0.005:
            return {"label": "person holding a knife", "confidence": knife_score}
            
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
                
                # Update EWMA
                instant_threat = prediction["confidence"] if prediction["label"] in VIOLENCE_LABELS else 0.0
                state.violence_score_ewma = (
                    (1.0 - state.alpha_ewma) * state.violence_score_ewma +
                    state.alpha_ewma * instant_threat
                )
                
                state.violence_history.append({
                    "time": current_time,
                    "label": prediction["label"],
                    "confidence": prediction["confidence"]
                })
                
                # Keep history within last 3.5 seconds
                while state.violence_history and (current_time - state.violence_history[0]["time"] > 3.5):
                    state.violence_history.popleft()
                    
                recent_hits = [
                    item for item in state.violence_history
                    if item["label"] in VIOLENCE_LABELS
                ]
                
                is_weapon = prediction["label"] in {"person holding a gun", "person holding a knife"}
                is_catastrophic = prediction["label"] in {"explosion", "fire in office", "fire on a street"}
                is_physical_fight = prediction["label"] in {"fight on a street", "street violence", "physical assault", "violence in office", "violence"}

                # Zone-adjusted sensitivity (LIMITATIONS.md Section 8 Phase 1.2)
                base_threshold = VIOLENCE_SCORE_THRESHOLD
                if state.zone_profile == "sports_relaxed":
                    base_threshold += 0.08  # Stricter in sports/gym areas to prevent false fight alarms
                elif state.zone_profile == "high_security":
                    base_threshold -= 0.05  # More sensitive in corridors, vaults, and entrances

                # Compute temporal span of recent violence hits (for 1.0s confirmation)
                time_span = (current_time - recent_hits[0]["time"]) if recent_hits else 0.0

                # 1.0-second sustained confirmation for fights/altercations
                confirmed_fight = (
                    len(recent_hits) >= 2
                    and time_span >= 0.95
                    and state.violence_score_ewma >= base_threshold
                )

                # Hybrid Instant Impact Detector (LIMITATIONS.md Section 2 & 7)
                # Bypasses 1.0s confirmation when sudden violent kinetic spike (motion > 12.0) occurs with high confidence
                instant_impact = (
                    is_physical_fight
                    and prediction["confidence"] >= 0.74
                    and state.motion_score >= 12.0
                )

                confirmed = (
                    (is_weapon and prediction["confidence"] >= WEAPON_GUN_CROP_THRESHOLD)
                    or (is_catastrophic and prediction["confidence"] >= VIOLENCE_INSTANT_THRESHOLD)
                    or instant_impact
                    or confirmed_fight
                )
                if prediction["label"] in VIOLENCE_LABELS and confirmed:
                    matching_scores = [
                        item["confidence"] for item in recent_hits
                        if item["label"] == prediction["label"]
                    ]
                    state.last_violence_label = prediction["label"]
                    # Multi-Frame Bayesian Confidence Compounding
                    bayesian_conf = _compute_bayesian_confidence(matching_scores)
                    state.last_violence_confidence = bayesian_conf
                    state.peak_threat_confidence = max(state.peak_threat_confidence, bayesian_conf)
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
                
                # 1. Process Base YOLO (Person, Knife)
                frame_person_heights = []
                has_knife = False
                for box in results[0].boxes:
                    cls = int(box.cls[0])
                    class_name = model.names[cls].lower()
                    confidence = round(float(box.conf[0]) * 100, 1)
                    coords = tuple(map(int, box.xyxy[0]))

                    if class_name == "person":
                        coords, track_id = _stabilize_person_box(state, coords, claimed_track_ids)
                        current_person_count += 1
                        
                        matched_face_bbox = None
                        person_name = None
                        for face_data in recognized_faces:
                            fx1, fy1, fx2, fy2 = face_data['bbox']
                            x1, y1, x2, y2 = coords
                            cx = (fx1 + fx2) / 2
                            cy = (fy1 + fy2) / 2
                            if x1 <= cx <= x2 and y1 <= cy <= y2:
                                matched_face_bbox = face_data['bbox']
                                if face_data['name'] != "Unknown":
                                    person_name = face_data['name']
                                break
                        
                        _, height_str = height_estimator.estimate_height(
                            coords, frame.shape, track_id=track_id, face_bbox=matched_face_bbox
                        )
                        frame_person_heights.append(height_str)
                        
                        if person_name:
                            class_name = person_name
                        else:
                            class_name = "person"
                    
                    if class_name == "knife":
                        has_knife = True
                        violence_detected_this_frame = True
                        state.last_violence_time = current_time
                        state.last_violence_label = class_name
                        state.last_violence_confidence = confidence
                        state.peak_threat_confidence = max(state.peak_threat_confidence, confidence)
                        _trigger_threat_actions(state, frame, current_time)

                    is_violent = is_violence_active(state, current_time)
                    
                    if class_name.startswith("knife"):
                        color = RED
                        threat = "CRITICAL"
                    else:
                        threat, color = get_threat_level(current_person_count, is_violent)
                    
                    new_boxes.append((coords, confidence, color, class_name))
                    if frame_event is None or threat == "CRITICAL":
                        frame_event = (class_name, confidence, threat)

                if frame_person_heights:
                    state.last_estimated_heights = frame_person_heights

                # 2. Process Custom YOLO Violence with Proximity & Temporal Confirmation
                raw_violence_hit = False
                if custom_results and len(custom_results[0].boxes) > 0:
                    for box in custom_results[0].boxes:
                        box_conf = float(box.conf[0])
                        if box_conf >= CUSTOM_VIOLENCE_CONFIDENCE:
                            # Violence/fights require multi-person interaction or knife weapon
                            has_proximity = _check_person_proximity(new_boxes)
                            if current_person_count >= 2 or has_proximity or has_knife:
                                raw_violence_hit = True
                                conf_pct = round(box_conf * 100, 1)
                                coords = tuple(map(int, box.xyxy[0]))
                                
                                state.consecutive_violence_hits += 1
                                if state.consecutive_violence_hits >= VIOLENCE_CONSECUTIVE_FRAMES_REQUIRED:
                                    violence_detected_this_frame = True
                                    state.last_violence_time = current_time
                                    state.last_violence_label = "violence"
                                    state.last_violence_confidence = conf_pct
                                    state.peak_threat_confidence = max(state.peak_threat_confidence, conf_pct)
                                    _trigger_threat_actions(state, frame, current_time)
                                    new_boxes.append((coords, conf_pct, RED, "violence"))
                                    frame_event = ("violence", conf_pct, "CRITICAL")
                                break

                if not raw_violence_hit:
                    state.consecutive_violence_hits = max(0, state.consecutive_violence_hits - 1)

                if not violence_detected_this_frame and not is_violence_active(state, current_time):
                    state.screenshot_count_this_event = 0

                state.person_count = current_person_count
                state.cached_boxes = new_boxes
                if frame_event:
                    event_label, event_confidence, threat = frame_event
                    add_detection(event_label, event_confidence, threat, state.name)
                    if threat == "CRITICAL":
                        state.peak_threat_confidence = max(
                            state.peak_threat_confidence,
                            event_confidence,
                            state.last_violence_confidence
                        )
                        effective_confidence = state.peak_threat_confidence
                        saved_id = save_detection(
                            label=event_label,
                            confidence=effective_confidence,
                            severity=threat,
                            camera=state.name,
                            cooldown=DETECTION_SAVE_COOLDOWN_SECONDS,
                            person_heights=state.last_estimated_heights,
                        )
                        if saved_id is not None:
                            state.last_db_save_time = current_time
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

        # Check for physical camera tampering (lens covered / blinded / blurred)
        if state.frame_count % 30 == 0:
            is_tampered, tamper_type, tamper_conf = detect_camera_tampering(frame)
            state.is_tampered = is_tampered
            state.tamper_type = tamper_type
            if is_tampered and (now - state.last_tamper_alert_time >= 30.0):
                state.last_tamper_alert_time = now
                save_detection(
                    label=f"Camera Tamper: {tamper_type}",
                    confidence=tamper_conf,
                    severity="CRITICAL",
                    camera=camera_name,
                    cooldown=30
                )

        for coords, confidence, color, class_name in state.cached_boxes:
            draw_box(frame, coords, confidence, color, class_name)

        is_violent = is_violence_active(state)
        threat, _ = get_threat_level(state.person_count, is_violent)
        
        if is_violent:
            cv2.putText(frame, f"CRITICAL: {state.last_violence_label.upper()}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, RED, 3)

        if state.is_tampered:
            cv2.putText(frame, f"⚠️ TAMPER ALERT: {state.tamper_type.upper()}", (10, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.65, RED, 2)

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
