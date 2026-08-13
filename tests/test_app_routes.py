import importlib
import sys
import types
import unittest


fake_detector = types.ModuleType("ai.detector")
fake_detector.detections = []
fake_detector.detect = lambda frame, **kwargs: frame
fake_detector.get_robot_status = lambda: {
    "dispatch": False,
    "camera": None,
    "threat": "LOW",
    "people": 0,
    "last_screenshot_time": 0,
}
fake_detector.remove_camera = lambda camera_id: None
sys.modules["ai.detector"] = fake_detector

app_module = importlib.import_module("app")


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def test_login_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_requires_login(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/"))

    def test_valid_login_opens_dashboard(self):
        response = self.client.post(
            "/",
            data={"email": "test@gmail.com", "password": "123"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"RAKSHAK", response.data.upper())

    def test_invalid_camera_id_returns_validation_error(self):
        response = self.client.post("/api/toggle_webcam", json={"camera_id": "invalid"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("camera_id", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
