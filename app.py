from flask import Flask, render_template, Response, jsonify, request, redirect, session
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

# Global variable to store the path of the uploaded video
uploaded_video_path = None

# Video control states
webcam_enabled = True
video_playing = True
video_seek_request = 0  # in seconds

# ====================================
# Video Streams
# ====================================
import platform

camera = None

def init_camera():
    global camera
    if camera is None or not camera.isOpened():
        if platform.system() == "Windows":
            camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        else:
            camera = cv2.VideoCapture(0)
        
        if camera is not None and camera.isOpened():
            print("✅ Camera opened successfully")
        else:
            print("⚠️ Running without local camera")
            camera = None

def generate_webcam_frames():
    global webcam_enabled, camera
    while True:
        if not webcam_enabled:
            if camera is not None:
                camera.release()
                camera = None
            import time
            import numpy as np
            blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(blank_frame, "Camera Disabled", (170, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            ret, buffer = cv2.imencode(".jpg", blank_frame)
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(0.5)
            continue
            
        if camera is None:
            init_camera()
            
        if camera is None:
            break
        success, frame = camera.read()
        if not success:
            continue

        # Detect uses cam_id=0 for webcam
        frame = detect(frame, camera_id="0", camera_name="Webcam (Live)")

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

def generate_uploaded_video_frames():
    global uploaded_video_path, video_playing, video_seek_request
    
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
            
        while uploaded_video_path is not None:
            if video_seek_request != 0:
                current_frame = cap.get(cv2.CAP_PROP_POS_FRAMES)
                new_frame = current_frame + (video_seek_request * fps)
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, new_frame))
                video_seek_request = 0
                
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

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/camera_feed")
def camera_feed():
    return Response(
        generate_webcam_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

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
    webcam_enabled = not webcam_enabled
    return jsonify({"status": "success", "webcam_enabled": webcam_enabled})

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

initialize_database()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5001,
        debug=True,
        use_reloader=False
    )