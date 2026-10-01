import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database


class DatabaseTests(unittest.TestCase):
    def test_database_path_is_relative_to_project(self):
        self.assertEqual(database.DB_PATH.parent, database.BASE_DIR / "database")

    def test_detection_lifecycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            test_db = Path(temp_dir) / "rakshak.db"
            with patch.object(database, "DB_PATH", test_db):
                database.initialize_database()
                detection_id = database.save_detection(
                    label="known person",
                    confidence=98.5,
                    severity="LOW",
                    camera="Test Camera",
                )

                self.assertEqual(database.get_detection_count(), 1)
                self.assertFalse(database.should_save_detection("known person", "Test Camera"))
                self.assertEqual(database.get_all_detections()[0]["id"], detection_id)

                database.delete_detection(detection_id)
                self.assertEqual(database.get_detection_count(), 0)

    def test_consecutive_detection_consolidation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            test_db = Path(temp_dir) / "rakshak.db"
            with patch.object(database, "DB_PATH", test_db):
                database.initialize_database()
                
                # First detection
                id1 = database.save_detection("Shiva", 95.0, "LOW", "Cam 1", cooldown=60)
                self.assertEqual(database.get_detection_count(), 1)
                self.assertEqual(database.get_all_detections()[0]["count"], 1)
                
                # Consecutive detection within cooldown (should update existing row)
                id2 = database.save_detection("Shiva", 98.0, "LOW", "Cam 1", cooldown=60)
                self.assertEqual(id1, id2)
                self.assertEqual(database.get_detection_count(), 1)
                self.assertEqual(database.get_all_detections()[0]["count"], 2)
                self.assertEqual(database.get_all_detections()[0]["confidence"], 98.0)
                
                # Detection after cooldown expires (cooldown=0 or negative simulates expiration)
                id3 = database.save_detection("Shiva", 92.0, "LOW", "Cam 1", cooldown=-1)
                self.assertNotEqual(id1, id3)
                self.assertEqual(database.get_detection_count(), 2)
                self.assertEqual(database.get_all_detections()[0]["count"], 1) # most recent row
                self.assertEqual(database.get_all_detections()[0]["confidence"], 92.0)


if __name__ == "__main__":
    unittest.main()
