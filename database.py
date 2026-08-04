import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path("database") / "rakshak.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    # ensure database directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS detections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT NOT NULL,
        confidence REAL,
        severity TEXT,
        camera TEXT,
        detected_at TEXT DEFAULT (CURRENT_TIMESTAMP)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        detection_id INTEGER,
        path TEXT,
        created_at TEXT DEFAULT (CURRENT_TIMESTAMP),
        FOREIGN KEY(detection_id) REFERENCES detections(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS recordings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        camera TEXT,
        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id TEXT,
        camera TEXT,
        threat TEXT,
        robot_status TEXT,
        report_date TEXT,
        report_time TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

def should_save_detection(label, camera, cooldown=5):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT detected_at
        FROM detections
        WHERE label = ? AND camera = ?
        ORDER BY id DESC
        LIMIT 1
    """, (label, camera))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return True

    last_detection = datetime.fromisoformat(row["detected_at"])

    return datetime.now() - last_detection > timedelta(seconds=cooldown)

def save_detection(label, confidence, severity, camera):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO detections
        (label, confidence, severity, camera)
        VALUES (?, ?, ?, ?)
    """, (
        label,
        confidence,
        severity,
        camera
    ))

    conn.commit()
    conn.close()

def save_snapshot(path):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO snapshots(path)
        VALUES (?)
    """, (
        path,
    ))

    conn.commit()
    conn.close()

def save_recording(filename, camera):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO recordings
        (filename, camera)
        VALUES (?, ?)
    """, (
        filename,
        camera
    ))

    conn.commit()
    conn.close()

def save_report(report_id, camera, threat, robot_status, report_date, report_time):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO reports
        (
            report_id,
            camera,
            threat,
            robot_status,
            report_date,
            report_time
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        report_id,
        camera,
        threat,
        robot_status,
        report_date,
        report_time
    ))

    conn.commit()
    conn.close()

def get_detection_count():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS total FROM detections")

    total = cursor.fetchone()["total"]

    conn.close()

    return total