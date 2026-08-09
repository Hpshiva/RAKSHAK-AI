from flask import Flask, render_template, Response, jsonify, request, redirect, session, send_from_directory
import cv2
import os
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from werkzeug.utils import secure_filename
from datetime import datetime
from ai.detector import detect
import ai.detector as detector
from database import initialize_database
from database import get_detection_count

app = Flask(__name__)
app.secret_key = "rakshak-ai-2026"

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

FACES_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faces')
os.makedirs(FACES_FOLDER, exist_ok=True)
app.config['FACES_FOLDER'] = FACES_FOLDER

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
        webcam_enabled[camera_id] = True
        
    if camera_id not in active_viewers:
        active_viewers[camera_id] = 0
    active_viewers[camera_id] += 1
        
    try:
        loading_count = 0
        while True:
            if not webcam_enabled.get(camera_id, True):
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
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        valid_login = (
            (email == "principal@rakshakai.edu" and password == "Rakshak@2026") or
            (email == "tech@rakshakai.edu" and password == "Tech@2026") or
            (email == "admin@rakshakai.edu" and password == "Admin@2026") or
            (email == "shrishail2071409" and password == "2071409")
        )

        if valid_login:
            session["logged_in"] = True
            session["user"] = email
            
            # Handle "Remember me"
            if request.form.get("remember"):
                session.permanent = True
            else:
                session.permanent = False
                
            return redirect("/dashboard")

        return render_template("login.html", error="Invalid email or password.")

    return render_template("login.html")

def send_real_otp_email(receiver_email, otp):
    sender_email = "shrishail2071409@gmail.com"
    # IMPORTANT: Generate a 16-letter App Password in your Google Account (2-Step Verification)
    sender_password = "nejjhnrddxqskhhe" 
    
    if sender_password == "YOUR_APP_PASSWORD_HERE":
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
        if email != "shrishail2071409@gmail.com":
            return render_template("forgot_password.html", error="This email is not registered as an admin.")
        
        otp = str(random.randint(100000, 999999))
        session["reset_otp"] = otp
        session["reset_email"] = email
        
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
    
    success = send_real_otp_email(email, otp)
    if not success:
        return render_template("verify_otp.html", email=email, error="Failed to resend email. Check backend App Password.")
        
    return render_template("verify_otp.html", email=email, error="OTP resent successfully! (Check your inbox)")

@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    if request.method == "POST":
        otp_entered = request.form.get("otp", "").strip()
        expected_otp = session.get("reset_otp")
        
        if expected_otp and otp_entered == expected_otp:
            session["logged_in"] = True
            session["user"] = "admin@rakshakai.edu"
            
            session.pop("reset_otp", None)
            session.pop("reset_email", None)
            
            return redirect("/dashboard")
        else:
            return render_template("verify_otp.html", error="Invalid OTP. Please try again.", email=session.get("reset_email"))
            
    if "reset_otp" not in session:
        return redirect("/forgot_password")
        
    return render_template("verify_otp.html", email=session.get("reset_email"))

@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect("/")
    
    return render_template("dashboard.html", has_uploaded_video=(uploaded_video_path is not None))

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
    # Force use of only the primary camera [0]
    # Scanning (0-3) on macOS often accidentally wakes up sleeping iPhones (Continuity Camera)
    # or virtual cameras, which results in phantom "grey box" video feeds on the dashboard.
    return jsonify({"cameras": [0]})

@app.route("/upload_video", methods=["POST"])
def upload_video():
    global uploaded_video_path
    if not session.get("logged_in"):
        return redirect("/")
        
    if 'video_file' not in request.files:
        return redirect("/dashboard")
        
    file = request.files['video_file']
    if file.filename == '':
        return redirect("/dashboard")
        
    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        uploaded_video_path = filepath
        
    return redirect("/dashboard")

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
    camera_id = data.get("camera_id", 0)
    
    current_state = webcam_enabled.get(camera_id, True)
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
    if seek_time is not None:
        video_seek_absolute = float(seek_time)
    return jsonify({"status": "ok"})

@app.route("/faces")
def faces():
    if not session.get("logged_in"):
        return redirect("/")
    return render_template("faces.html")

@app.route("/api/upload_face", methods=["POST"])
def upload_face():
    if "file" not in request.files or "name" not in request.form:
        return jsonify({"error": "Missing file or name"}), 400
        
    file = request.files["file"]
    name = request.form["name"].strip()
    
    if file.filename == "" or not name:
        return jsonify({"error": "Invalid file or name"}), 400
        
    filename = secure_filename(f"{name}_{file.filename}")
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
                # name is usually everything before the last underscore, 
                # but because we formatted it as {name}_{original}, we can just split.
                parts = filename.split('_')
                name = parts[0] if len(parts) > 1 else filename.split('.')[0]
                faces_list.append({"name": name, "filename": filename})
    return jsonify(faces_list)

@app.route("/api/delete_face", methods=["POST"])
def delete_face():
    data = request.get_json()
    filename = data.get("filename")
    if filename:
        filepath = os.path.join(app.config["FACES_FOLDER"], secure_filename(filename))
        if os.path.exists(filepath):
            os.remove(filepath)
            # Reload faces
            try:
                from ai.detector import face_recognizer
                face_recognizer.load_faces(app.config["FACES_FOLDER"])
            except:
                pass
            return jsonify({"status": "deleted"})
    return jsonify({"error": "File not found"}), 404

@app.route("/faces_img/<filename>")
def faces_img(filename):
    return send_from_directory(app.config["FACES_FOLDER"], filename)

initialize_database()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5001,
        debug=True,
        use_reloader=False
    )