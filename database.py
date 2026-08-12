import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path("database") / "rakshak.db"

db_lock = threading.Lock()

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
        count INTEGER DEFAULT 1,
        detected_at TEXT DEFAULT (CURRENT_TIMESTAMP)
    )
    """)
    try:
        cursor.execute("ALTER TABLE detections ADD COLUMN count INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass

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

    cursor.execute("DELETE FROM detections WHERE label = 'person'")
    conn.commit()
    conn.close()

def should_save_detection(label, camera, cooldown=60):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT datetime(detected_at, 'localtime') as detected_at
        FROM detections
        WHERE label = ? AND camera = ?
        ORDER BY id DESC
        LIMIT 1
    """, (label, camera))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return True

    # SQLite returns YYYY-MM-DD HH:MM:SS, format for fromisoformat needs T divider
    dt_str = row["detected_at"].replace(" ", "T")
    last_detection = datetime.fromisoformat(dt_str)

    return datetime.now() - last_detection > timedelta(seconds=cooldown)

def save_detection(label, confidence, severity, camera):
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, label, camera, count 
            FROM detections 
            ORDER BY id DESC 
            LIMIT 1
        """)
        row = cursor.fetchone()
        
        if row and row["label"] == label and row["camera"] == camera:
            cursor.execute("""
                UPDATE detections 
                SET confidence = ?, severity = ?, count = count + 1, detected_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (confidence, severity, row["id"]))
            detection_id = row["id"]
        else:
            cursor.execute("""
                INSERT INTO detections (label, confidence, severity, camera, count)
                VALUES (?, ?, ?, ?, 1)
            """, (label, confidence, severity, camera))
            detection_id = cursor.lastrowid
            
        conn.commit()
        conn.close()
    return detection_id

def get_recent_face_detections(limit=5):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT label, camera, detected_at, severity
        FROM detections
        WHERE label != 'person' AND label != 'knife' AND label != 'gun' AND label NOT LIKE 'person%'
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def save_snapshot(path):

    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO snapshots (path)
            VALUES (?)
        """, (path,))
        conn.commit()
        conn.close()

def save_recording(filename, camera):

    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO recordings (filename, camera)
            VALUES (?, ?)
        """, (filename, camera))
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

def get_all_detections(severity_filter=None, limit=200):
    conn = get_connection()
    cursor = conn.cursor()
    
    if severity_filter:
        cursor.execute("""
            SELECT id, label, confidence, severity, camera, count, datetime(detected_at, 'localtime') as detected_at
            FROM detections
            WHERE severity = ?
            ORDER BY id DESC
            LIMIT ?
        """, (severity_filter, limit))
    else:
        cursor.execute("""
            SELECT id, label, confidence, severity, camera, count, datetime(detected_at, 'localtime') as detected_at
            FROM detections
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_detection(detection_id):
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM detections WHERE id = ?", (detection_id,))
        conn.commit()
        conn.close()

def get_analytics_summary():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Severity counts
    cursor.execute("SELECT severity, COUNT(*) as count FROM detections GROUP BY severity")
    severity_counts = {row["severity"]: row["count"] for row in cursor.fetchall()}
    
    # 2. Label distribution
    cursor.execute("SELECT label, COUNT(*) as count FROM detections GROUP BY label")
    label_counts = {row["label"]: row["count"] for row in cursor.fetchall()}
    
    # 3. Last 7 days alerts count (daily)
    cursor.execute("""
        SELECT date(detected_at, 'localtime') as day, COUNT(*) as count
        FROM detections
        WHERE detected_at >= datetime('now', '-7 days')
        GROUP BY day
        ORDER BY day ASC
    """)
    daily_counts = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return {
        "severity_counts": severity_counts,
        "label_counts": label_counts,
        "daily_counts": daily_counts
    }

def clear_all_detections():
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM detections")
        conn.commit()
        conn.close()