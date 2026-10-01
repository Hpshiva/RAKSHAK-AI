from database import get_connection, save_detection
import sqlite3

def test():
    conn = get_connection()
    cursor = conn.cursor()
    label = "Test Label"
    camera = "Test Cam"
    
    # insert first
    id1 = save_detection(label, 90.0, "LOW", camera)
    print("inserted id1:", id1)
    
    # insert second immediately
    id2 = save_detection(label, 90.0, "LOW", camera)
    print("inserted id2:", id2)
    
    cursor.execute("SELECT id, count, detected_at FROM detections WHERE label = ? ORDER BY id DESC LIMIT 2", (label,))
    rows = cursor.fetchall()
    for row in rows:
        print(dict(row))
        
test()
