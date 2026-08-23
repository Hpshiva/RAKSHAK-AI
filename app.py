from flask import Flask, render_template, Response, jsonify, request, redirect, session, send_file, send_from_directory
from io import BytesIO
import cv2
import os
import random
import re
import smtplib
import time
import hmac
import urllib.request
import urllib.error
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from werkzeug.utils import secure_filename
from ai.detector import detect
import ai.detector as detector
from database import initialize_database
from database import (
    get_all_detections,
    get_detection_count,
    delete_detection,
    get_incident_report_data,
    get_recent_face_detections,
    save_report,
)
from report_generator import build_incident_report
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "rakshak-ai-2026-fallback")
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload size
SESSION_TIMEOUT_SECONDS = 300


def env_float(name, default, minimum=0.0):
    try:
        return max(minimum, float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        app.logger.warning("Invalid %s value; using %s", name, default)
        return float(default)


ESP32_BASE_URL = os.environ.get("ESP32_BASE_URL", "http://192.168.1.118").rstrip("/")
ESP32_TIMEOUT_SECONDS = env_float("ESP32_TIMEOUT_SECONDS", 0.5, minimum=0.1)
ESP32_RETRY_SECONDS = env_float("ESP32_RETRY_SECONDS", 1, minimum=0.0)
last_esp32_attempt_time = 0.0


def send_esp32_command(command):
    global last_esp32_attempt_time
    command = str(command).strip().lower()

    if command not in {"safe", "alert","off"}:
        return False

    now = time.monotonic()
    if now - last_esp32_attempt_time < ESP32_RETRY_SECONDS:
        return False
    last_esp32_attempt_time = now

    try:
        url = f"{ESP32_BASE_URL}/{command}"

        with urllib.request.urlopen(url, timeout=ESP32_TIMEOUT_SECONDS) as response:
            result = response.read().decode("utf-8")

        print(f"✅ ESP32 {command.upper()}: {result}")
        return True

    except Exception as error:
        print(f"⚠️ ESP32 communication failed: {error}")
        return False

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

REPORTS_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')
os.makedirs(REPORTS_FOLDER, exist_ok=True)
app.config['REPORTS_FOLDER'] = REPORTS_FOLDER

FACES_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faces')
os.makedirs(FACES_FOLDER, exist_ok=True)
app.config['FACES_FOLDER'] = FACES_FOLDER

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "rakshakadmin@gmail.com").strip().lower()
LOGIN_ACCOUNTS = {
    "principal@rakshakai.edu": os.environ.get("PRINCIPAL_LOGIN_PASSWORD", "Rakshak@2026"),
    "admin@rakshakai.edu": os.environ.get("ADMIN_LOGIN_PASSWORD", "Admin@2026"),
    ADMIN_EMAIL: os.environ.get("ADMIN_LOGIN_PASSWORD", "Admin@2026"),
    "test@gmail.com": "123",
}
# Trivial "test@gmail.com" / "123" credential is now hardcoded for testing.

def verify_login(email, password):
    expected = LOGIN_ACCOUNTS.get(str(email).strip().lower())
    return bool(expected) and hmac.compare_digest(str(password), expected)

@app.before_request
def enforce_session_timeout():
    """Expire authenticated sessions after five minutes."""
    public_endpoints = {"login", "forgot_password", "resend_otp", "verify_otp", "static"}
    if not session.get("logged_in"):
        if request.endpoint and request.endpoint not in public_endpoints:
            if (
                request.path.startswith("/api/")
                or request.path in {"/robot_status", "/detections"}
                or request.path.endswith("_feed")
                or request.path.startswith("/camera_feed/")
            ):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect("/")
        return None

    login_time = session.get("login_time")
    if login_time is None or time.time() - login_time >= SESSION_TIMEOUT_SECONDS:
        session.clear()
        if request.path.startswith("/api/") or request.path in {"/robot_status", "/detections"}:
            return jsonify({"error": "Session expired"}), 401
        return redirect("/")
    # Sliding window: an active session keeps renewing itself so users aren't
    # cut off mid-task. Without this, every session hard-expired exactly
    # SESSION_TIMEOUT_SECONDS after login regardless of activity.
    session["login_time"] = time.time()
    return None

# Global variable to store the path of the uploaded video
uploaded_video_path = None

# Video control states
webcam_enabled = {} # dict of camera_id (int) -> bool
video_playing = True
video_seek_request = 0  # in seconds
video_seek_absolute = None # in seconds
video_current_time = 0.0 # in seconds
video_duration = 0.0 # in seconds

# ====================================
# Video Streams
# ====================================
import platform

class ZeroLatencyCamera:
    """
    Constantly grabs frames in the background to ensure the AI always 
    processes the absolute latest frame with zero delay/buffer lag.
    """
    def __init__(self, camera_id):
        if platform.system() == "Windows":
            self.capture = cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)
        else:
            self.capture = cv2.VideoCapture(camera_id)
            
        self.latest_frame = None
        self.running = self.capture.isOpened()
        
        if self.running:
            self.thread = threading.Thread(target=self._update, daemon=True)
            self.thread.start()

    def _update(self):
        while self.running:
            ret, frame = self.capture.read()
            if ret:
                self.latest_frame = frame
            else:
                import time
                time.sleep(0.1) # Wait for Mac camera to warm up

    def read(self):
        if self.latest_frame is not None:
            return True, self.latest_frame
        return False, None

    def release(self):
        self.running = False
        if hasattr(self, 'thread'):
            self.thread.join(timeout=1.0)
        self.capture.release()
        self.latest_frame = None

    def isOpened(self):
        return self.capture.isOpened()

cameras = {} # dict of camera_id (int) -> ZeroLatencyCamera

def get_camera(camera_id):
    global cameras
    
    if camera_id not in cameras or cameras[camera_id] is None or not cameras[camera_id].isOpened():
        cap = ZeroLatencyCamera(camera_id)
        
        if cap.isOpened():
            cameras[camera_id] = cap
            print(f"✅ Zero-Latency Camera {camera_id} opened successfully")
        else:
            print(f"⚠️ Failed to open camera {camera_id}")
            cameras[camera_id] = None
            
    return cameras[camera_id]

active_viewers = {} # dict of camera_id (int) -> int

def generate_webcam_frames(camera_id=0):
    global webcam_enabled, cameras, active_viewers
    
    # Initialize state if not present
    if camera_id not in webcam_enabled:
        webcam_enabled[camera_id] = False
        
    if camera_id not in active_viewers:
        active_viewers[camera_id] = 0
    active_viewers[camera_id] += 1
        
    try:
        loading_count = 0
        while True:
            if not webcam_enabled.get(camera_id, False):
                if camera_id in cameras and cameras[camera_id] is not None:
                    cameras[camera_id].release()
                    cameras[camera_id] = None
                import time
                import numpy as np
                blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(blank_frame, f"Camera {camera_id} Disabled", (130, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                ret, buffer = cv2.imencode(".jpg", blank_frame)
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                time.sleep(0.5)
                continue
                
            cap = get_camera(camera_id)
                
            if cap is None:
                import time
                import numpy as np
                blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(blank_frame, f"Camera {camera_id} Not Found", (130, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                ret, buffer = cv2.imencode(".jpg", blank_frame)
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                time.sleep(1)
                continue
                
            success, frame = cap.read()
            if not success:
                import time
                time.sleep(0.1)
                loading_count += 1
                # Yield a loading frame every 500ms so Flask can detect if client disconnects
                if loading_count >= 5:
                    import numpy as np
                    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(blank_frame, f"Waking up Camera {camera_id}...", (100, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                    ret, buffer = cv2.imencode(".jpg", blank_frame)
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                    loading_count = 0
                continue
            
            # Reset loading count if successful
            loading_count = 0

            # Detect uses cam_id for tracking threats independently
            frame = detect(frame, camera_id=str(camera_id), camera_name=f"Webcam {camera_id} (Live)")
            sync_esp32_with_robot_status()

            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret:
                continue

            frame_bytes = buffer.tobytes()
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' +
                frame_bytes +
                b'\r\n'
            )
            
            # CRITICAL: Prevent 10,000 FPS infinite loop!
            # Since ZeroLatencyCamera is non-blocking, we must pace the output to ~30 FPS
            import time
            time.sleep(0.033)
            
    finally:
        active_viewers[camera_id] -= 1
        if active_viewers[camera_id] <= 0:
            active_viewers[camera_id] = 0
            if camera_id in cameras and cameras[camera_id] is not None:
                print(f"🛑 No active viewers. Turning off Camera {camera_id}")
                cameras[camera_id].release()
                cameras[camera_id] = None

def generate_uploaded_video_frames():
    global uploaded_video_path, video_playing, video_seek_request, video_seek_absolute, video_current_time, video_duration
    
    last_frame_bytes = None
    
    while True:
        if uploaded_video_path is None or not os.path.exists(uploaded_video_path):
            import time
            time.sleep(1)
            continue
            
        cap = cv2.VideoCapture(uploaded_video_path)
        cam_name = "Uploaded Video"
        cam_id = "upload_1"
        
        # Get FPS for playback pacing
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps == 0 or fps != fps:
            fps = 30
            
        video_duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
            
        while uploaded_video_path is not None:
            if video_seek_absolute is not None:
                new_frame = video_seek_absolute * fps
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(new_frame, cap.get(cv2.CAP_PROP_FRAME_COUNT) - 1)))
                video_seek_absolute = None
                video_seek_request = 0

            elif video_seek_request != 0:
                current_frame = cap.get(cv2.CAP_PROP_POS_FRAMES)
                new_frame = current_frame + (video_seek_request * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(new_frame, cap.get(cv2.CAP_PROP_FRAME_COUNT) - 1)))
                video_seek_request = 0
                
            video_current_time = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
                
            if not video_playing:
                import time
                # A newly opened MJPEG connection may start while playback is
                # paused and therefore has no cached frame yet. Read and send
                # a preview frame instead of leaving the browser on a black
                # screen waiting indefinitely for its first response bytes.
                if last_frame_bytes is None:
                    success, preview_frame = cap.read()
                    if success:
                        ret, preview_buffer = cv2.imencode(".jpg", preview_frame)
                        if ret:
                            last_frame_bytes = preview_buffer.tobytes()
                if last_frame_bytes:
                    yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + last_frame_bytes + b'\r\n')
                time.sleep(0.1)
                continue
                
            success, frame = cap.read()
            if not success:
                # Loop the video
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
                
            frame = detect(frame, camera_id=cam_id, camera_name=cam_name)
            
            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret:
                continue
                
            frame_bytes = buffer.tobytes()
            last_frame_bytes = frame_bytes
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' +
                frame_bytes +
                b'\r\n'
            )
            
            # Pace the video to its original FPS since detect is async
            import time
            time.sleep(1.0 / fps)
        
        if cap is not None:
            cap.release()

# ====================================
# Routes
# ====================================

@app.route("/esp32/safe")
def esp32_safe():
    success = send_esp32_command("safe")
    return jsonify({
        "status": "success" if success else "failed",
        "command": "safe"
    })


@app.route("/esp32/alert")
def esp32_alert():
    success = send_esp32_command("alert")
    return jsonify({
        "status": "success" if success else "failed",
        "command": "alert"
    })

@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect("/dashboard")

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        valid_login = verify_login(email, password)

        if valid_login:
            session["logged_in"] = True
            session["user"] = email
            session["login_time"] = time.time()
            session.permanent = False
                
            return redirect("/dashboard")

        return render_template("login.html", error="Invalid email or password.")

    return render_template("login.html")

def send_real_otp_email(receiver_email, otp):
    sender_email = os.environ.get("SMTP_EMAIL", "")
    sender_password = os.environ.get("SMTP_PASSWORD", "")
    
    if not sender_email or not sender_password or sender_password == "YOUR_APP_PASSWORD_HERE":
        print("\n" + "=" * 50)
        print("⚠️ NO APP PASSWORD PROVIDED - USING MOCK EMAIL ⚠️")
        print(f"📧 [MOCK EMAIL] To: {receiver_email}")
        print(f"🔑 Your Rakshak AI Admin Login OTP is: {otp}")
        print("=" * 50 + "\n")
        return True
        
    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg['Subject'] = "Rakshak AI - Your Admin Login OTP"
        
        body = f"Hello,\n\nYour one-time password (OTP) for Rakshak AI Admin Login is: {otp}\n\nDo not share this code with anyone."
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if email != ADMIN_EMAIL:
            return render_template("forgot_password.html", error="This email is not registered as an admin.")
        
        otp = str(random.randint(100000, 999999))
        session["reset_otp"] = otp
        session["reset_email"] = email
        session["reset_otp_attempts"] = 0

        success = send_real_otp_email(email, otp)
        if not success:
            return render_template("forgot_password.html", error="Failed to send email. Check backend App Password in app.py.")

        return redirect("/verify_otp")

    return render_template("forgot_password.html")

@app.route("/resend_otp")
def resend_otp():
    email = session.get("reset_email")
    if not email:
        return redirect("/forgot_password")

    otp = str(random.randint(100000, 999999))
    session["reset_otp"] = otp
    session["reset_otp_attempts"] = 0

    success = send_real_otp_email(email, otp)
    if not success:
        return render_template("verify_otp.html", email=email, error="Failed to resend email. Check backend App Password.")
        
    return render_template("verify_otp.html", email=email, error="OTP resent successfully! (Check your inbox)")

OTP_MAX_ATTEMPTS = 5

@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    if request.method == "POST":
        otp_entered = request.form.get("otp", "").strip()
        expected_otp = session.get("reset_otp")

        if expected_otp and hmac.compare_digest(otp_entered, expected_otp):
            session["logged_in"] = True
            session["user"] = session.get("reset_email", ADMIN_EMAIL)
            session["login_time"] = time.time()
            session.permanent = False

            session.pop("reset_otp", None)
            session.pop("reset_email", None)
            session.pop("reset_otp_attempts", None)

            return redirect("/dashboard")

        # Lock the OTP out after too many wrong guesses instead of allowing
        # unlimited brute-force attempts against a 6-digit code.
        attempts = session.get("reset_otp_attempts", 0) + 1
        session["reset_otp_attempts"] = attempts
        if not expected_otp or attempts >= OTP_MAX_ATTEMPTS:
            session.pop("reset_otp", None)
            session.pop("reset_email", None)
            session.pop("reset_otp_attempts", None)
            return render_template(
                "forgot_password.html",
                error="Too many incorrect attempts. Please request a new OTP.",
            )
        return render_template(
            "verify_otp.html",
            error=f"Invalid OTP. Please try again. ({OTP_MAX_ATTEMPTS - attempts} attempt(s) left)",
            email=session.get("reset_email"),
        )


    if "reset_otp" not in session:
        return redirect("/forgot_password")
        
    return render_template("verify_otp.html", email=session.get("reset_email"))

@app.route("/dashboard")
def dashboard():
    global last_esp32_state

    if not session.get("logged_in"):
        return redirect("/")

    if send_esp32_command("safe"):
        last_esp32_state = "safe"

    return render_template(
        "dashboard.html",
        has_uploaded_video=(uploaded_video_path is not None)
    )

@app.route("/about")
def about():
    if not session.get("logged_in"):
        return redirect("/")
    return render_template("about.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/camera_feed/<int:camera_id>")
def camera_feed(camera_id):
    if camera_id != 0:
        return "Camera not found", 404
    return Response(
        generate_webcam_frames(camera_id),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@app.route("/api/cameras")
def get_cameras():
    return jsonify({"cameras": [0]})

@app.route("/upload_video", methods=["POST"])
def upload_video():
    global uploaded_video_path, video_playing, video_seek_request
    global video_seek_absolute, video_current_time, video_duration
    if not session.get("logged_in"):
        return redirect("/")
        
    if 'video_file' not in request.files:
        return redirect("/video_analysis")
        
    file = request.files['video_file']
    if file.filename == '':
        return redirect("/video_analysis")

    extension = os.path.splitext(file.filename)[1].lower()
    if extension not in {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm"}:
        return jsonify({"error": "Unsupported video format"}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    capture = cv2.VideoCapture(filepath)
    frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    source_fps = capture.get(cv2.CAP_PROP_FPS)
    is_valid_video = capture.isOpened() and frame_count > 0
    capture.release()
    if not is_valid_video:
        os.remove(filepath)
        return jsonify({"error": "The uploaded file is not a valid video"}), 400
    uploaded_video_path = filepath
    # Every new upload starts from the beginning in the playing state. Without
    # this reset, a previously paused video leaves the new stream black.
    video_playing = True
    video_seek_request = 0
    video_seek_absolute = 0.0
    video_current_time = 0.0
    video_duration = frame_count / max(source_fps, 1)
        
    return redirect("/video_analysis")

@app.route("/uploaded_video_feed")
def uploaded_video_feed():
    return Response(
        generate_uploaded_video_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@app.route("/robot_status")
def robot_status():
    return jsonify(detector.get_robot_status())

last_esp32_state = None
last_esp32_heartbeat = 0.0
ESP32_HEARTBEAT_SECONDS = 2.0

def sync_esp32_with_robot_status():
    global last_esp32_state, last_esp32_heartbeat

    status = detector.get_robot_status()
    threat = str(status.get("threat", "LOW")).upper()

    desired_state = "safe" if threat == "LOW" else "alert"

    now = time.monotonic()

    state_changed = desired_state != last_esp32_state
    heartbeat_due = (now - last_esp32_heartbeat) >= ESP32_HEARTBEAT_SECONDS

    if not state_changed and not heartbeat_due:
        return

    if send_esp32_command(desired_state):
        last_esp32_state = desired_state
        last_esp32_heartbeat = now

@app.route("/detections")
def detections():
    return jsonify(detector.detections)

@app.route("/api/recent_faces")
def recent_faces():
    faces = get_recent_face_detections(5)
    return jsonify(faces)

@app.route("/api/stats")
def api_stats():
    return {
        "totalDetections": get_detection_count()
    }

@app.route("/analytics")
def analytics():
    if not session.get("logged_in"):
        return redirect("/")
    return render_template("analytics.html")

@app.route("/api/analytics/logs")
def analytics_logs():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        page = max(1, request.args.get("page", 1, type=int))
        page_size = min(100, max(10, request.args.get("page_size", 50, type=int)))
        return jsonify(get_all_detections(
            search=request.args.get("search", "").strip(),
            severity=request.args.get("severity", "").strip().upper(),
            date=request.args.get("date", "").strip(),
            page=page,
            page_size=page_size,
        ))
    except Exception as error:
        app.logger.exception("Unable to load analytics logs")
        return jsonify({"error": str(error)}), 500

@app.route("/api/analytics/logs/<int:detection_id>", methods=["DELETE"])
def delete_analytics_log(detection_id):
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    password = str((request.get_json(silent=True) or {}).get("password", ""))
    if not password:
        return jsonify({"error": "Password is required"}), 400
    if not verify_login(session.get("user", ""), password):
        return jsonify({"error": "Incorrect password"}), 403
    if not delete_detection(detection_id):
        return jsonify({"error": "Log not found"}), 404
    return jsonify({"status": "success", "deleted_id": detection_id})

@app.route("/generate_report")
def generate_report():
    if not session.get("logged_in"):
        return redirect("/")
    detection_id = request.args.get("detection_id", type=int)
    requested_camera = request.args.get("camera", "").strip()
    camera = "Uploaded Video" if requested_camera == "Uploaded Video" else None
    incident = get_incident_report_data(detection_id, camera=camera)
    if not incident:
        message = (
            "No critical uploaded-video incident is available for reporting."
            if camera else "No critical incident is available for reporting."
        )
        return message, 404

    snapshot = incident.get("snapshot") or {}
    if not snapshot.get("student_names"):
        for state in detector.camera_states.values():
            if state.name == incident.get("camera") and state.last_recognized_names:
                snapshot["student_names"] = ", ".join(state.last_recognized_names)
                break
    if not snapshot.get("student_names") and os.path.isfile(snapshot.get("path", "")):
        snapshot_frame = cv2.imread(snapshot["path"])
        if snapshot_frame is not None:
            recognized = detector.face_recognizer.recognize_faces(snapshot_frame)
            names = list(dict.fromkeys(
                face["name"] for face in recognized
                if face.get("name") and face["name"] != "Unknown"
            ))
            if names:
                snapshot["student_names"] = ", ".join(names)
    incident["snapshot"] = snapshot

    pdf_bytes = build_incident_report(incident)
    occurred = str(incident.get("detected_at", "incident")).replace(":", "-").replace(" ", "_")
    filename = secure_filename(f"Rakshak_AI_Incident_{incident['id']}_{occurred}.pdf")
    report_path = os.path.join(app.config["REPORTS_FOLDER"], filename)
    with open(report_path, "wb") as report_file:
        report_file.write(pdf_bytes)
    now = time.localtime()
    save_report(
        f"RK-{incident['id']:06d}",
        incident.get("camera", "Unknown"),
        incident.get("label", "Critical"),
        "DISPATCHED",
        time.strftime("%Y-%m-%d", now),
        time.strftime("%H:%M:%S", now),
    )
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
        max_age=0,
    )

# ====================================
# Video Controls APIs
# ====================================
@app.route("/api/toggle_webcam", methods=["POST"])
def toggle_webcam():
    global last_esp32_state

    data = request.get_json(silent=True) or {}
    try:
        camera_id = int(data.get("camera_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid camera ID"}), 400
    if camera_id != 0:
        return jsonify({"error": "Camera not available"}), 404

    current_state = webcam_enabled.get(camera_id, False)
    desired_state = data.get("enabled")
    webcam_enabled[camera_id] = bool(desired_state) if isinstance(desired_state, bool) else not current_state

    # Camera OFF = ESP32 SAFE
    if not webcam_enabled[camera_id]:
        if send_esp32_command("off"):
            last_esp32_state = "off"
    
    return jsonify({"status": "success", "camera_id": camera_id, "webcam_enabled": webcam_enabled[camera_id]})

@app.route("/api/dashboard_closed", methods=["POST"])
def dashboard_closed():
    global last_esp32_state

    if send_esp32_command("off"):
        last_esp32_state = "off"

    return ("", 204)

@app.route("/threat_screenshot/<filename>")
def threat_screenshot(filename):
    if not session.get("logged_in"):
        return redirect("/")
    safe_filename = secure_filename(filename)
    if not safe_filename.startswith("violence_") or not safe_filename.lower().endswith(".jpg"):
        return "Screenshot not found", 404
    return send_from_directory(detector.SNAPSHOT_DIR, safe_filename)

@app.route("/api/video/play", methods=["POST"])
def video_play():
    global video_playing
    video_playing = True
    return jsonify({"status": "success", "video_playing": True})

@app.route("/api/video/pause", methods=["POST"])
def video_pause():
    global video_playing
    video_playing = False
    return jsonify({"status": "success", "video_playing": False})

@app.route("/api/video/seek/<seconds>", methods=["POST"])
def video_seek(seconds):
    global video_seek_request
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid seek value"}), 400
    if not -300 <= seconds <= 300:
        return jsonify({"error": "Seek value is out of range"}), 400
    video_seek_request = seconds
    return jsonify({"status": "success", "seek": seconds})

@app.route("/api/video/close", methods=["POST"])
def video_close():
    global uploaded_video_path
    uploaded_video_path = None
    import ai.detector as detector
    detector.remove_camera("upload_1")
    return jsonify({"status": "success"})

@app.route("/api/video_progress")
def api_video_progress():
    return jsonify({
        "current": video_current_time,
        "total": video_duration,
        "playing": video_playing
    })

@app.route("/api/video_seek_absolute", methods=["POST"])
def api_video_seek_absolute():
    global video_seek_absolute
    data = request.get_json(silent=True) or {}
    seek_time = data.get("time")
    try:
        if seek_time is not None:
            video_seek_absolute = max(0.0, float(seek_time))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid seek time"}), 400
    return jsonify({"status": "ok"})

@app.route("/faces")
def faces():
    if not session.get("logged_in"):
        return redirect("/")
    return render_template("faces.html")

@app.route("/video_analysis")
def video_analysis():
    if not session.get("logged_in"):
        return redirect("/")
    
    # We pass the uploaded_video_path to know whether to show the player or the upload form
    return render_template("video_analysis.html", has_uploaded_video=uploaded_video_path is not None)

def _sanitize_face_component(value):
    """Sanitize a name/role fragment for use inside the composite
    ``name__role__photo`` filename. Collapsing repeated underscores keeps a
    sanitized value from accidentally containing our own '__' delimiter
    (e.g. a name with two adjacent special characters), which would
    otherwise misalign the name/role split done in /api/faces and
    /api/edit_face.
    """
    cleaned = secure_filename(value)
    return re.sub(r"_+", "_", cleaned).strip("_")


@app.route("/api/upload_face", methods=["POST"])
def upload_face():
    if "file" not in request.files or "name" not in request.form or "role" not in request.form:
        return jsonify({"error": "Missing file, name, or role"}), 400

    file = request.files["file"]
    name = request.form["name"].strip()
    role = request.form["role"].strip()

    allowed_roles = {"Student", "Staff", "Unknown"}
    extension = os.path.splitext(file.filename)[1].lower()
    if file.filename == "" or not name or role not in allowed_roles:
        return jsonify({"error": "Invalid file, name, or role"}), 400
    if extension not in {".jpg", ".jpeg", ".png"}:
        return jsonify({"error": "Only JPG and PNG images are supported"}), 400

    safe_name = _sanitize_face_component(name)
    safe_role = _sanitize_face_component(role)
    if not safe_name:
        return jsonify({"error": "Invalid file, name, or role"}), 400
    filename = secure_filename(f"{safe_name}__{safe_role}__{file.filename}")
    filepath = os.path.join(app.config["FACES_FOLDER"], filename)
    file.save(filepath)
    
    # Reload the face recognizer
    try:
        from ai.detector import face_recognizer
        face_recognizer.load_faces(app.config["FACES_FOLDER"])
    except Exception as e:
        print("Error reloading faces:", e)
        
    return jsonify({"status": "success", "filename": filename})

@app.route("/api/faces")
def api_faces():
    faces_list = []
    if os.path.exists(app.config["FACES_FOLDER"]):
        for filename in os.listdir(app.config["FACES_FOLDER"]):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                if '__' in filename:
                    parts = filename.split('__')
                    name = parts[0]
                    role = parts[1]
                else:
                    parts = filename.split('_')
                    name = parts[0] if len(parts) > 1 else filename.split('.')[0]
                    role = ""
                faces_list.append({"name": name, "role": role, "filename": filename})
    return jsonify(faces_list)

@app.route("/api/delete_face", methods=["POST"])
def delete_face():
    data = request.get_json(silent=True) or {}
    filename = data.get("filename")
    if filename:
        filepath = os.path.join(app.config["FACES_FOLDER"], secure_filename(filename))
        if os.path.exists(filepath):
            os.remove(filepath)
            # Reload faces
            try:
                from ai.detector import face_recognizer
                face_recognizer.load_faces(app.config["FACES_FOLDER"])
            except Exception as error:
                app.logger.warning("Face recognizer reload failed after delete: %s", error)
            return jsonify({"status": "deleted"})
    return jsonify({"error": "File not found"}), 404

@app.route("/api/edit_face", methods=["POST"])
def edit_face():
    data = request.get_json(silent=True) or {}
    old_filename = data.get("old_filename")
    new_name = data.get("new_name")
    new_role = data.get("new_role")
    
    new_name = str(new_name or "").strip()
    new_role = str(new_role or "").strip()
    if not old_filename or not new_name or new_role not in {"Student", "Staff", "Unknown"}:
        return jsonify({"error": "Missing required fields"}), 400
        
    old_filepath = os.path.join(app.config["FACES_FOLDER"], secure_filename(old_filename))
    if not os.path.exists(old_filepath):
        return jsonify({"error": "File not found"}), 404
        
    # Extract original part of filename to keep
    if '__' in old_filename:
        original = old_filename.split('__')[-1]
    else:
        # Fallback for older formats like name_Photo.jpg
        original = old_filename.split('_', 1)[-1] if '_' in old_filename else old_filename

    safe_name = _sanitize_face_component(new_name)
    safe_role = _sanitize_face_component(new_role)
    if not safe_name:
        return jsonify({"error": "Missing required fields"}), 400
    new_filename = secure_filename(f"{safe_name}__{safe_role}__{original}")
    new_filepath = os.path.join(app.config["FACES_FOLDER"], new_filename)
    if new_filepath != old_filepath and os.path.exists(new_filepath):
        return jsonify({"error": "A face with this name and role already exists"}), 409
    
    os.rename(old_filepath, new_filepath)
    
    # Reload faces
    try:
        from ai.detector import face_recognizer
        face_recognizer.load_faces(app.config["FACES_FOLDER"])
    except Exception as e:
        print("Error reloading faces:", e)
        
    return jsonify({"status": "success"})

@app.route("/faces_img/<filename>")
def faces_img(filename):
    return send_from_directory(app.config["FACES_FOLDER"], secure_filename(filename))

initialize_database()

@app.errorhandler(404)
def not_found_error(error):
    return "Page not found", 404

@app.errorhandler(500)
def internal_error(error):
    return "Internal server error", 500

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=7860,
        debug=True,
        use_reloader=False
    )
