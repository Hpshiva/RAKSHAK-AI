import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "database" / "rakshak.db"

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
        detected_at TEXT DEFAULT (CURRENT_TIMESTAMP)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        detection_id INTEGER,
        path TEXT,
        camera TEXT,
        incident_label TEXT,
        student_names TEXT,
        created_at TEXT DEFAULT (CURRENT_TIMESTAMP),
        FOREIGN KEY(detection_id) REFERENCES detections(id)
    )
    """)

    snapshot_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(snapshots)").fetchall()
    }
    for column, definition in {
        "camera": "TEXT",
        "incident_label": "TEXT",
        "student_names": "TEXT",
    }.items():
        if column not in snapshot_columns:
            cursor.execute(f"ALTER TABLE snapshots ADD COLUMN {column} {definition}")

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

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    return now_utc - last_detection > timedelta(seconds=cooldown)

def save_detection(label, confidence, severity, camera, cooldown=5):
    if str(severity).upper() != "CRITICAL":
        return None
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT detected_at FROM detections
            WHERE label = ? AND camera = ? AND severity = ?
            ORDER BY id DESC LIMIT 1
        """, (label, camera, severity))
        latest = cursor.fetchone()
        if latest:
            last_detection = datetime.fromisoformat(latest["detected_at"])
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            if now_utc - last_detection <= timedelta(seconds=cooldown):
                conn.close()
                return None
        cursor.execute("""
            INSERT INTO detections (label, confidence, severity, camera)
            VALUES (?, ?, ?, ?)
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

def save_snapshot(path, camera=None, incident_label=None, student_names=None):

    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO snapshots (path, camera, incident_label, student_names)
            VALUES (?, ?, ?, ?)
        """, (
            path,
            camera,
            incident_label,
            ", ".join(student_names or []),
        ))
        conn.commit()
        conn.close()

def get_incident_report_data(detection_id=None, camera=None):
    """Return a critical incident and its closest saved violence screenshot."""
    conn = get_connection()
    cursor = conn.cursor()
    if detection_id is None and camera:
        detection = cursor.execute("""
            SELECT * FROM detections
            WHERE severity = 'CRITICAL' AND camera = ?
            ORDER BY id DESC LIMIT 1
        """, (camera,)).fetchone()
    elif detection_id is None:
        detection = cursor.execute("""
            SELECT * FROM detections
            WHERE severity = 'CRITICAL'
            ORDER BY id DESC LIMIT 1
        """).fetchone()
    else:
        detection = cursor.execute("""
            SELECT * FROM detections
            WHERE id = ? AND severity = 'CRITICAL'
        """, (detection_id,)).fetchone()
    if not detection:
        conn.close()
        return None

    # Cap how far apart the snapshot and detection timestamps may be. Without
    # this bound, "closest in time" would still match and silently attach an
    # unrelated screenshot from a much earlier/later incident on the same
    # camera whenever no snapshot from this incident exists.
    snapshot = cursor.execute("""
        SELECT * FROM snapshots
        WHERE (camera = ? OR camera IS NULL)
          AND ABS(strftime('%s', created_at) - strftime('%s', ?)) <= 120
        ORDER BY ABS(strftime('%s', created_at) - strftime('%s', ?)), id DESC
        LIMIT 1
    """, (detection["camera"], detection["detected_at"], detection["detected_at"])).fetchone()

    # The detector now captures a short burst of screenshots per incident
    # (see MAX_SCREENSHOTS_PER_EVENT in ai/detector.py). Pull all of them
    # within the same time window, in chronological order, so a generated
    # report can show how the incident progressed rather than one frame.
    snapshots = cursor.execute("""
        SELECT * FROM snapshots
        WHERE (camera = ? OR camera IS NULL)
          AND ABS(strftime('%s', created_at) - strftime('%s', ?)) <= 120
        ORDER BY created_at ASC, id ASC
        LIMIT 6
    """, (detection["camera"], detection["detected_at"])).fetchall()

    result = dict(detection)
    result["snapshot"] = dict(snapshot) if snapshot else None
    result["snapshots"] = [dict(row) for row in snapshots] if snapshots else (
        [dict(snapshot)] if snapshot else []
    )
    conn.close()
    return result

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

def delete_detection(detection_id):
    """Delete exactly one analytics event and report whether it existed."""
    with db_lock:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM detections WHERE id = ?", (detection_id,))
        deleted = cursor.rowcount == 1
        conn.commit()
        conn.close()
    return deleted

def get_all_detections(search="", severity="", date="", page=1, page_size=50):
    """Return event-based history, grouping frame-level duplicate detections."""
    conn = get_connection()
    cursor = conn.cursor()
    conditions = []
    params = []
    if search:
        conditions.append("(label LIKE ? OR camera LIKE ?)")
        term = f"%{search}%"
        params.extend([term, term])
    if severity:
        conditions.append("severity = ?")
        params.append(severity)
    if date:
        conditions.append("date(detected_at) = ?")
        params.append(date)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    events_cte = """
        WITH ordered AS (
            SELECT *,
                CASE WHEN
                    LAG(detected_at) OVER (
                        PARTITION BY lower(label), camera, severity ORDER BY detected_at, id
                    ) IS NULL
                    OR (julianday(detected_at) - julianday(
                        LAG(detected_at) OVER (
                            PARTITION BY lower(label), camera, severity ORDER BY detected_at, id
                        )
                    )) * 86400 > 5
                THEN 1 ELSE 0 END AS new_event
            FROM detections
            WHERE severity = 'CRITICAL'
        ), grouped AS (
            SELECT *, SUM(new_event) OVER (
                PARTITION BY lower(label), camera, severity ORDER BY detected_at, id
            ) AS event_group
            FROM ordered
        ), events AS (
            SELECT MAX(id) AS id, label, ROUND(AVG(confidence), 1) AS confidence,
                   severity, camera, MAX(detected_at) AS detected_at,
                   COUNT(*) AS frame_count
            FROM grouped
            GROUP BY lower(label), camera, severity, event_group
        )
    """
    cursor.execute(f"{events_cte} SELECT COUNT(*) AS total FROM events {where}", params)
    total = cursor.fetchone()["total"]
    offset = (page - 1) * page_size
    cursor.execute(f"""
        {events_cte}
        SELECT id, label, confidence, severity, camera, detected_at, frame_count
        FROM events
        {where}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """, [*params, page_size, offset])
    rows = cursor.fetchall()
    cursor.execute(f"""
        {events_cte}
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN lower(label) = 'person' THEN 1 ELSE 0 END) AS people,
            SUM(CASE WHEN severity = 'CRITICAL' THEN 1 ELSE 0 END) AS critical,
            COUNT(DISTINCT camera) AS cameras
        FROM events
    """)
    summary = dict(cursor.fetchone())
    conn.close()
    return {"logs": [dict(row) for row in rows], "total": total, "summary": summary}
