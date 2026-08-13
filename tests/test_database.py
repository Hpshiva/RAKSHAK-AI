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

    def test_initialize_does_not_erase_person_alerts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            test_db = Path(temp_dir) / "rakshak.db"
            with patch.object(database, "DB_PATH", test_db):
                database.initialize_database()
                database.save_detection("person", 95.0, "LOW", "Main Gate")

                database.initialize_database()

                alerts = database.get_all_detections()
                self.assertEqual(len(alerts), 1)
                self.assertEqual(alerts[0]["label"], "person")

    def test_notification_timestamp_is_explicit_utc(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            test_db = Path(temp_dir) / "rakshak.db"
            with patch.object(database, "DB_PATH", test_db):
                database.initialize_database()
                database.save_detection("violence in office", 91.0, "CRITICAL", "Webcam 0")

                notification = database.get_recent_face_detections(1)[0]

                self.assertIsInstance(notification["id"], int)
                self.assertRegex(
                    notification["detected_at"],
                    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
                )


if __name__ == "__main__":
    unittest.main()
