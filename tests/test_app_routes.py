import importlib
import sys
import types
import unittest

from jinja2 import StrictUndefined


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
        app_module.app.jinja_env.undefined = StrictUndefined
        self.client = app_module.app.test_client()

    def test_login_page_loads(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_dashboard_requires_login(self):
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/"))

    def test_password_reset_page_loads(self):
        response = self.client.get("/forgot_password")
        self.assertEqual(response.status_code, 200)

    def test_valid_login_opens_dashboard(self):
        response = self.client.post(
            "/",
            data={"email": "admin@rakshakai.edu", "password": "Admin@2026"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"RAKSHAK", response.data.upper())

    def test_removed_legacy_login_is_rejected(self):
        response = self.client.post(
            "/",
            data={"email": "removed-user@example.invalid", "password": "removed-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid email or password", response.data)

    def test_principal_cannot_delete_alerts(self):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["user"] = "principal@rakshakai.edu"
            session["role"] = "principal"

        response = self.client.delete("/api/alerts_history/1")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"], "Admin access required")

    def test_admin_can_delete_alerts(self):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["user"] = "admin@rakshakai.edu"
            session["role"] = "admin"

        response = self.client.delete("/api/alerts_history/999999")
        self.assertEqual(response.status_code, 200)

    def test_authenticated_pages_disable_browser_cache(self):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["user"] = "unauthorized-user@example.invalid"

        response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn(b"navigationEntry.type === 'reload'", response.data)

    def test_all_authenticated_pages_render(self):
        with self.client.session_transaction() as session:
            session["logged_in"] = True
            session["user"] = "unauthorized-user@example.invalid"

        for path in (
            "/dashboard",
            "/robot",
            "/map",
            "/analytics",
            "/alerts",
            "/about",
            "/faces",
            "/video_analysis",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)

    def test_invalid_camera_id_returns_validation_error(self):
        response = self.client.post("/api/toggle_webcam", json={"camera_id": "invalid"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("camera_id", response.get_json()["error"])

    def test_camera_switcher_receives_configured_cameras(self):
        response = self.client.get("/api/cameras")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["cameras"], [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
