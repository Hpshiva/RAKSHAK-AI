from flask import Flask, render_template, Response, jsonify, request, redirect, session, send_from_directory
import cv2
import math
import os
import secrets
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from werkzeug.utils import secure_filename
from ai.detector import detect
import ai.detector as detector
from database import get_detection_count, get_recent_face_detections, initialize_database, get_all_detections, delete_detection, get_analytics_summary, clear_all_detections
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "rakshak-ai-2026-fallback")
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload size


@app.after_request
def prevent_authenticated_page_caching(response):
    """Prevent protected pages being revealed by browser back/forward cache."""
    if session.get("logged_in"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

FACES_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faces')
os.makedirs(FACES_FOLDER, exist_ok=True)
app.config['FACES_FOLDER'] = FACES_FOLDER

ALLOWED_VIDEO_EXTENSIONS = {"avi", "m4v", "mkv", "mov", "mp4", "webm"}
ALLOWED_IMAGE_EXTENSIONS = {"jpeg", "jpg", "png"}


def has_allowed_extension(filename, allowed_extensions):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions

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

import threading

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
        if not math.isfinite(fps) or fps <= 0:
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

@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect("/dashboard")

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        admin_email = os.environ.get("ADMIN_LOGIN_EMAIL", "admin@rakshakai.edu").strip().lower()
        admin_password = os.environ.get("ADMIN_LOGIN_PASSWORD", "")
        principal_email = os.environ.get("PRINCIPAL_LOGIN_EMAIL", "principal@rakshakai.edu").strip().lower()
        principal_password = os.environ.get("PRINCIPAL_LOGIN_PASSWORD", "")

        role = None
        if email == admin_email and secrets.compare_digest(password, admin_password):
            role = "admin"
        elif email == principal_email and secrets.compare_digest(password, principal_password):
            role = "principal"

        if role:
            session["logged_in"] = True
            session["user"] = email
            session["role"] = role
            
            # Handle "Remember me"
            if request.form.get("remember"):
                session.permanent = True
            else:
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
        
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        admin_email = os.environ.get("ADMIN_EMAIL", "rakshakadmin@gmail.com").strip().lower()
        
        if email != admin_email:
            return render_template(
                "forgot_password.html",
                error="This email is not registered as an admin.",
                email=email,
            )
        
        otp = f"{secrets.randbelow(900000) + 100000:06d}"
        session["reset_otp"] = otp
        session["reset_email"] = email
        session["reset_otp_expires_at"] = time.time() + 600
        session["reset_otp_attempts"] = 0
        
        success = send_real_otp_email(email, otp)
        if not success:
            return render_template(
                "forgot_password.html",
                error="Failed to send email. Check the SMTP configuration.",
                email=email,
            )
            
        return redirect("/verify_otp")
        
    return render_template("forgot_password.html")

@app.route("/resend_otp")
def resend_otp():
    email = session.get("reset_email")
    if not email:
        return redirect("/forgot_password")
        
    otp = f"{secrets.randbelow(900000) + 100000:06d}"
    session["reset_otp"] = otp
    session["reset_otp_expires_at"] = time.time() + 600
    session["reset_otp_attempts"] = 0
    
    success = send_real_otp_email(email, otp)
    if not success:
        return render_template("verify_otp.html", email=email, error="Failed to resend email. Check backend App Password.")
        
    return render_template("verify_otp.html", email=email, error="OTP resent successfully! (Check your inbox)")

@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    if request.method == "POST":
        otp_entered = request.form.get("otp", "").strip()
        expected_otp = session.get("reset_otp")
        expires_at = session.get("reset_otp_expires_at", 0)
        attempts = session.get("reset_otp_attempts", 0)

        if time.time() > expires_at:
            session.pop("reset_otp", None)
            session.pop("reset_otp_expires_at", None)
            return render_template(
                "verify_otp.html",
                error="OTP expired. Please request a new code.",
                email=session.get("reset_email"),
            )

        if attempts >= 5:
            session.clear()
            return redirect("/forgot_password")

        if expected_otp and otp_entered == expected_otp:
            session["logged_in"] = True
            session["user"] = session.get("reset_email")
            session["role"] = "admin"
            
            session.pop("reset_otp", None)
            session.pop("reset_email", None)
            session.pop("reset_otp_expires_at", None)
            session.pop("reset_otp_attempts", None)
            
            return redirect("/dashboard")
        else:
            session["reset_otp_attempts"] = attempts + 1
            return render_template("verify_otp.html", error="Invalid OTP. Please try again.", email=session.get("reset_email"))
            
    if "reset_otp" not in session:
        return redirect("/forgot_password")
        
    return render_template("verify_otp.html", email=session.get("reset_email"))

@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect("/")
    return render_template("dashboard.html")

@app.route("/robot")
def robot():
    if not session.get("logged_in"):
        return redirect("/")
    return render_template("placeholder.html", title="Robot Dispatch")

@app.route("/map")
def map():
    if not session.get("logged_in"):
        return redirect("/")
    return render_template("placeholder.html", title="Campus Map")

@app.route("/analytics")
def analytics():
    if not session.get("logged_in"):
        return redirect("/")
    return render_template("analytics.html")

@app.route("/alerts")
def alerts():
    if not session.get("logged_in"):
        return redirect("/")
    return render_template("alerts.html")

@app.route("/api/alerts_history", methods=["GET"])
def api_alerts_history():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    
    severity_filter = request.args.get("severity")
    if severity_filter == "All" or not severity_filter:
        severity_filter = None
        
    alerts_data = get_all_detections(severity_filter=severity_filter)
    return jsonify(alerts_data)

@app.route("/api/alerts_history/<int:alert_id>", methods=["DELETE"])
def api_delete_alert(alert_id):
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    if session.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403
    
    delete_detection(alert_id)
    return jsonify({"status": "success"})

@app.route("/api/clear_all_detections", methods=["POST"])
def api_clear_all_detections():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    if session.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403
    
    clear_all_detections()
    detector.detections.clear()
    return jsonify({"status": "success"})

@app.route("/api/analytics_metrics", methods=["GET"])
def api_analytics_metrics():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
        
    summary = get_analytics_summary()
    return jsonify(summary)

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
    return Response(
        generate_webcam_frames(camera_id),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

@app.route("/api/cameras")
def get_cameras():
    configured_ids = os.environ.get("CAMERA_IDS", "0,1,2,3")
    cameras_list = []
    for value in configured_ids.split(","):
        try:
            camera_id = int(value.strip())
        except ValueError:
            continue
        if camera_id >= 0 and camera_id not in cameras_list:
            cameras_list.append(camera_id)
    return jsonify({"cameras": cameras_list or [0]})

@app.route("/api/webcam_status/<int:camera_id>")
def webcam_status(camera_id):
    return jsonify({"camera_id": camera_id, "webcam_enabled": webcam_enabled.get(camera_id, False)})

@app.route("/upload_video", methods=["POST"])
def upload_video():
    global uploaded_video_path
    if not session.get("logged_in"):
        return redirect("/")
        
    if 'video_file' not in request.files:
        return redirect("/video_analysis")
        
    file = request.files['video_file']
    if file.filename == '':
        return redirect("/video_analysis")
        
    if not has_allowed_extension(file.filename, ALLOWED_VIDEO_EXTENSIONS):
        return jsonify({"error": "Unsupported video file type"}), 400

    filename = secure_filename(file.filename)
    if not filename:
        return jsonify({"error": "Invalid filename"}), 400

    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    cap = cv2.VideoCapture(filepath)
    is_valid_video = cap.isOpened() and cap.get(cv2.CAP_PROP_FRAME_COUNT) > 0
    cap.release()
    if not is_valid_video:
        os.remove(filepath)
        return jsonify({"error": "The uploaded file is not a readable video"}), 400

    uploaded_video_path = filepath
        
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

# ====================================
# Video Controls APIs
# ====================================
@app.route("/api/toggle_webcam", methods=["POST"])
def toggle_webcam():
    global webcam_enabled
    data = request.get_json() or {}
    try:
        camera_id = int(data.get("camera_id", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "camera_id must be an integer"}), 400
    
    current_state = webcam_enabled.get(camera_id, False)
    webcam_enabled[camera_id] = not current_state
    
    return jsonify({"status": "success", "camera_id": camera_id, "webcam_enabled": webcam_enabled[camera_id]})

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

@app.route("/api/video/seek/<int:seconds>", methods=["POST"])
def video_seek(seconds):
    global video_seek_request
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
    data = request.get_json() or {}
    seek_time = data.get("time")
    if seek_time is None:
        return jsonify({"error": "Missing time"}), 400
    try:
        video_seek_absolute = max(0.0, float(seek_time))
    except (TypeError, ValueError):
        return jsonify({"error": "time must be a number"}), 400
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

@app.route("/api/upload_face", methods=["POST"])
def upload_face():
    if "file" not in request.files or "name" not in request.form or "role" not in request.form:
        return jsonify({"error": "Missing file, name, or role"}), 400
        
    file = request.files["file"]
    name = request.form["name"].strip()
    role = request.form["role"].strip()
    
    if file.filename == "" or not name or not role:
        return jsonify({"error": "Invalid file, name, or role"}), 400

    if not has_allowed_extension(file.filename, ALLOWED_IMAGE_EXTENSIONS):
        return jsonify({"error": "Unsupported image file type"}), 400
        
    filename = secure_filename(f"{name}__{role}__{file.filename}")
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
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401
    if session.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403

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
                app.logger.warning("Could not reload known faces: %s", error)
            return jsonify({"status": "deleted"})
    return jsonify({"error": "File not found"}), 404

@app.route("/api/edit_face", methods=["POST"])
def edit_face():
    data = request.get_json(silent=True) or {}
    old_filename = data.get("old_filename")
    new_name = data.get("new_name")
    new_role = data.get("new_role")
    
    if not old_filename or not new_name or not new_role:
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
        
    new_filename = secure_filename(f"{new_name.strip()}__{new_role.strip()}__{original}")
    new_filepath = os.path.join(app.config["FACES_FOLDER"], new_filename)
    
    if os.path.exists(new_filepath) and os.path.abspath(new_filepath) != os.path.abspath(old_filepath):
        return jsonify({"error": "A face with that name and role already exists"}), 409

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
    return send_from_directory(app.config["FACES_FOLDER"], filename)

initialize_database()

@app.errorhandler(404)
def not_found_error(error):
    return render_template('about.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('about.html'), 500

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5002,
        debug=True,
        use_reloader=False
    )
