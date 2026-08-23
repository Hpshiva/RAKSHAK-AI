import sqlite3
import os
from pathlib import Path

def clean_database():
    db_path = Path('database/rakshak.db')
    snapshots_dir = Path('snapshots_violence')
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Delete rows with missing values
    print("Deleting snapshots with missing detection_id...")
    cursor.execute("DELETE FROM snapshots WHERE detection_id IS NULL OR detection_id = ''")
    print(f"Deleted {cursor.rowcount} rows with missing detection_id.")
    
    # 2. Delete duplicate detections (exact duplicates except ID)
    print("Deleting exact duplicate detections...")
    cursor.execute("""
        DELETE FROM detections 
        WHERE id NOT IN (
            SELECT MIN(id) 
            FROM detections 
            GROUP BY label, confidence, severity, camera, detected_at
        )
    """)
    print(f"Deleted {cursor.rowcount} duplicate detections.")
    
    # Delete duplicate snapshots
    cursor.execute("""
        DELETE FROM snapshots 
        WHERE id NOT IN (
            SELECT MIN(id) 
            FROM snapshots 
            GROUP BY detection_id, path, camera
        )
    """)
    
    # Check for snapshots pointing to non-existent files or invalid paths (C:\)
    # We will just fetch all paths, and if they don't match a local file, we delete the row
    cursor.execute("SELECT id, path FROM snapshots")
    rows = cursor.fetchall()
    deleted_paths = 0
    valid_filenames = set()
    for row in rows:
        snapshot_id, path = row
        filename = os.path.basename(path.replace('\\', '/'))
        local_path = snapshots_dir / filename
        if not local_path.exists():
            cursor.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
            deleted_paths += 1
        else:
            valid_filenames.add(filename)
    
    print(f"Deleted {deleted_paths} snapshots with missing files on disk.")
    
    conn.commit()
    conn.close()

    # 3. Delete orphaned image files
    print("Checking for orphaned images in snapshots_violence/...")
    orphaned_files = 0
    if snapshots_dir.exists():
        for file in snapshots_dir.iterdir():
            if file.is_file() and file.name not in valid_filenames:
                file.unlink()
                orphaned_files += 1
                
    print(f"Deleted {orphaned_files} orphaned image files.")
    print("Cleanup complete.")

if __name__ == '__main__':
    clean_database()
