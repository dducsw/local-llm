import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.database import save_session, get_session, delete_session
from app.config import ADMIN_PASSWORD, VIEWER_PASSWORD


class TestAuthEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_admin_login_success(self):
        resp = self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": ADMIN_PASSWORD or "admin123"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("role"), "admin")
        self.assertTrue(data.get("token", "").startswith("sess_"))

    def test_viewer_login_success(self):
        resp = self.client.post("/api/auth/login", json={
            "username": "viewer",
            "password": VIEWER_PASSWORD or "viewer123"
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "ok")
        self.assertEqual(data.get("role"), "viewer")
        self.assertTrue(data.get("token", "").startswith("sess_"))

    def test_login_invalid_password(self):
        resp = self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "wrong-password-999"
        })
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        self.assertIn("detail", data)

    def test_auth_me_verification_and_logout(self):
        # 1. Login to get token
        login_resp = self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": ADMIN_PASSWORD or "admin123"
        })
        token = login_resp.json()["token"]

        # 2. Check /me with valid token
        me_resp = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me_resp.status_code, 200)
        self.assertTrue(me_resp.json().get("authenticated"))
        self.assertEqual(me_resp.json().get("role"), "admin")

        # 3. Logout
        logout_resp = self.client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(logout_resp.status_code, 200)

        # 4. Check /me after logout (should be unauthenticated)
        me_after = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertFalse(me_after.json().get("authenticated"))

    def setUp(self):
        from app.state import LOGIN_ATTEMPTS
        LOGIN_ATTEMPTS.clear()

    def test_database_session_persistence(self):
        import time
        test_token = "sess_unittest_persistence_token"
        save_session(test_token, "test_user", "admin", expires_at=time.time() + 300)

        sess = get_session(test_token)
        self.assertIsNotNone(sess)
        self.assertEqual(sess["username"], "test_user")
        self.assertEqual(sess["role"], "admin")

        delete_session(test_token)
        self.assertIsNone(get_session(test_token))


if __name__ == "__main__":
    unittest.main()
