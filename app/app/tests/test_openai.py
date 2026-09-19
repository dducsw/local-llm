import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.config import ADMIN_TOKEN, ADMIN_PASSWORD


class TestOpenAIEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.auth_header = {"Authorization": f"Bearer {ADMIN_TOKEN or ADMIN_PASSWORD or 'admin123'}"}

    def test_models_list_endpoint(self):
        resp = self.client.get("/v1/models")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("object"), "list")
        self.assertIsInstance(data.get("data"), list)
        self.assertTrue(len(data["data"]) > 0)
        # Check first model structure
        m = data["data"][0]
        self.assertIn("id", m)
        self.assertIn("status", m)
        self.assertIn("owned_by", m)

    def test_chat_completions_missing_auth(self):
        resp = self.client.post("/v1/chat/completions", json={
            "model": "qwen3.5-9b",
            "messages": [{"role": "user", "content": "Hello"}]
        })
        self.assertEqual(resp.status_code, 401)
        err = resp.json().get("detail", {}).get("error", {})
        self.assertEqual(err.get("type"), "authentication_error")

    def test_chat_completions_invalid_key(self):
        resp = self.client.post(
            "/v1/chat/completions",
            json={
                "model": "qwen3.5-9b",
                "messages": [{"role": "user", "content": "Hello"}]
            },
            headers={"Authorization": "Bearer sk-invalid-key-9999"}
        )
        self.assertEqual(resp.status_code, 401)
        err = resp.json().get("detail", {}).get("error", {})
        self.assertEqual(err.get("type"), "authentication_error")

    def test_chat_completions_unknown_model(self):
        resp = self.client.post(
            "/v1/chat/completions",
            json={
                "model": "non-existent-super-llm-999",
                "messages": [{"role": "user", "content": "Hello"}]
            },
            headers=self.auth_header
        )
        self.assertEqual(resp.status_code, 404)
        err = resp.json().get("detail", {}).get("error", {})
        self.assertEqual(err.get("type"), "invalid_request_error")

    def test_chat_completions_invalid_json(self):
        resp = self.client.post(
            "/v1/chat/completions",
            content="invalid-raw-string-not-json",
            headers={**self.auth_header, "Content-Type": "application/json"}
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
