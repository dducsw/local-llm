import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app.config import ADMIN_PASSWORD, VIEWER_PASSWORD


class TestRBAC(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        from app.state import LOGIN_ATTEMPTS
        LOGIN_ATTEMPTS.clear()

        # Obtain Viewer token
        v_resp = cls.client.post("/api/auth/login", json={
            "username": "viewer",
            "password": VIEWER_PASSWORD or "viewer123"
        })
        cls.viewer_token = v_resp.json()["token"]

        LOGIN_ATTEMPTS.clear()
        # Obtain Admin token
        a_resp = cls.client.post("/api/auth/login", json={
            "username": "admin",
            "password": ADMIN_PASSWORD or "admin123"
        })
        cls.admin_token = a_resp.json()["token"]

    def test_unauthenticated_access_rejected(self):
        unauth_client = TestClient(app)
        resp = unauth_client.get("/api/slurm/nodes")
        self.assertEqual(resp.status_code, 401)
        data = resp.json()
        self.assertIn("error", data.get("detail", {}))

    def test_viewer_can_read_slurm_nodes(self):
        resp = self.client.get("/api/slurm/nodes", headers={"Authorization": f"Bearer {self.viewer_token}"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("nodes", resp.json())

    def test_viewer_can_read_slurm_queue(self):
        resp = self.client.get("/api/slurm/queue", headers={"Authorization": f"Bearer {self.viewer_token}"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("jobs", resp.json())

    def test_viewer_forbidden_to_cancel_job(self):
        resp = self.client.post(
            "/api/slurm/jobs/999999/cancel",
            headers={"Authorization": f"Bearer {self.viewer_token}"}
        )
        self.assertEqual(resp.status_code, 403)
        err = resp.json().get("detail", {}).get("error", {})
        self.assertEqual(err.get("type"), "permission_denied")

    def test_viewer_forbidden_to_submit_job(self):
        resp = self.client.post(
            "/api/slurm/jobs/submit",
            json={"model": "test"},
            headers={"Authorization": f"Bearer {self.viewer_token}"}
        )
        self.assertEqual(resp.status_code, 403)
        err = resp.json().get("detail", {}).get("error", {})
        self.assertEqual(err.get("type"), "permission_denied")

    @patch("app.routers.slurm.run_slurm_cli_async")
    def test_admin_permitted_on_protected_actions(self, mock_cli):
        # Admin should pass RBAC check; mock prevents any actual sbatch job from being submitted to HPC
        mock_cli.return_value = (0, "Submitted batch job 999999", "")
        resp = self.client.post(
            "/api/slurm/jobs/submit",
            json={"model": "test"},
            headers={"Authorization": f"Bearer {self.admin_token}"}
        )
        self.assertEqual(resp.status_code, 200)

    def test_slurm_logs_access(self):
        # 1. REST logs with Authorization header
        resp = self.client.get(
            "/api/slurm/logs/mock_test_1",
            headers={"Authorization": f"Bearer {self.viewer_token}"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("log", resp.json())

        # 2. REST logs with query parameter token
        resp2 = self.client.get(f"/api/slurm/logs/mock_test_1?token={self.viewer_token}")
        self.assertEqual(resp2.status_code, 200)
        self.assertIn("log", resp2.json())

        # 3. REST logs fallback (graceful browser dashboard access)
        unauth_client = TestClient(app)
        resp3 = unauth_client.get("/api/slurm/logs/mock_test_1")
        self.assertEqual(resp3.status_code, 200)
        self.assertIn("log", resp3.json())


if __name__ == "__main__":
    unittest.main()
