# Rakshak AI

AI-powered campus surveillance with live/offline video analysis, critical-event logging, face identification, snapshots, notifications, and PDF incident reports.

## Project structure

```text
ai/                   Detection, violence classification, face recognition
database/             Local SQLite database
evaluation/           Accuracy benchmark and evaluation labels
faces/                Registered face images (local data)
models/               YOLO and face-detection model files
reports/              Generated incident reports
Snapshots_violence/   Automatically captured critical-event frames
static/               CSS, JavaScript, fonts, and image assets
templates/            Flask HTML templates
uploads/              Videos uploaded through the web interface
videos/               Local sample/evaluation videos
app.py                 Flask application and routes
database.py            Database access layer
report_generator.py    PDF incident-report builder
train.py               Optional YOLO training entry point
wsgi.py                Production WSGI entry point
```

## Setup

```bash
python -m venv venv
venv/Scripts/python -m pip install -r requirements.txt
venv/Scripts/python app.py
```

On Linux/macOS, activate the environment or run `./run_app.sh`.

Open `http://127.0.0.1:7860`.

## Configuration

Copy `.env.example` to `.env` and set login, Flask, and SMTP values. Do not commit `.env`, registered faces, uploaded videos, snapshots, reports, database files, or model weights.

## Main features

- Authenticated dashboard with five-minute session timeout
- Webcam and uploaded-video analysis
- YOLOv8 person detection and CLIP-based critical-event classification
- Known-face registration and editing
- Critical-only analytics logs
- Automatic violence screenshots
- Downloadable PDF incident reports
- Email OTP recovery and in-app critical notifications
