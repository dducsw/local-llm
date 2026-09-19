import unittest
from fastapi.testclient import TestClient
from app.main import app


class TestSecurityAndSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_security_headers_present(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(resp.headers.get("x-frame-options"), "SAMEORIGIN")
        self.assertEqual(resp.headers.get("x-xss-protection"), "1; mode=block")

    def test_healthz_and_version(self):
        h_resp = self.client.get("/healthz")
        self.assertEqual(h_resp.status_code, 200)
        self.assertEqual(h_resp.json(), {"status": "ok"})

        v_resp = self.client.get("/version")
        self.assertEqual(v_resp.status_code, 200)
        self.assertIn("version", v_resp.json())
        self.assertEqual(v_resp.json().get("status"), "running")

    def test_error_sanitization_structure(self):
        # Trigger an invalid path to verify error JSON envelope
        resp = self.client.get("/api/non-existent-random-endpoint")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("detail", resp.json())


if __name__ == "__main__":
    unittest.main()
