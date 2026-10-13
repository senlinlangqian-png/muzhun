import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from muzhun.server import create_app
from muzhun import __version__


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app(Path(self.temp.name))
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def test_page_and_status(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        status = self.client.get("/api/status").json()
        self.assertEqual(status["max_duration"], 7200)
        self.assertIn("token", status)
        self.assertEqual(status["version"], __version__)

    def test_generated_review_page_is_inline_and_confined_to_job(self):
        folder = Path(self.temp.name) / "outputs" / "1234567890abcdef" / "delivery-C"
        folder.mkdir(parents=True)
        (folder / "review.html").write_text("<!doctype html><h1>Review</h1>", "utf-8")
        response = self.client.get("/api/jobs/1234567890abcdef/files/delivery-C/review.html")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertNotIn("attachment", response.headers.get("content-disposition", ""))

    def test_mutation_requires_same_page_token(self):
        self.assertEqual(self.client.post("/api/demo", json={}).status_code, 403)

    def test_missing_demo_is_clear(self):
        token = self.client.get("/api/status").json()["token"]
        response = self.client.post("/api/demo", headers={"X-Muzhun-Token": token}, json={})
        self.assertEqual(response.status_code, 404)

    def test_file_and_job_path_confinement(self):
        for url in ("/api/jobs/not-a-job", "/api/jobs/1234567890abcdef/files/README.md", "/api/jobs/1234567890abcdef/files/../../pyproject.toml"):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_unexpected_upload_type(self):
        token = self.client.get("/api/status").json()["token"]
        response = self.client.post("/api/jobs", headers={"X-Muzhun-Token": token}, files={"video": ("evil.html", b"hello", "text/html")})
        self.assertEqual(response.status_code, 400)

    def test_moving_demo_copies_its_own_video_and_subtitle(self):
        examples = Path(self.temp.name) / "examples"
        examples.mkdir()
        (examples / "dynamic-demo.mp4").write_bytes(b"controlled-moving-video")
        (examples / "dynamic-input.srt").write_text("moving-panel-subtitle", "utf-8")
        status = self.client.get("/api/status").json()
        self.assertTrue(status["moving_demo_available"])
        with patch("muzhun.server.ThreadPoolExecutor.submit") as submit:
            response = self.client.post("/api/demo", headers={"X-Muzhun-Token": status["token"]}, json={"kind": "moving"})
        self.assertEqual(response.status_code, 200)
        folder = Path(self.temp.name) / "outputs" / response.json()["id"]
        self.assertEqual((folder / "source.mp4").read_bytes(), b"controlled-moving-video")
        self.assertEqual(submit.call_args.args[4], "moving-panel-subtitle")
        self.assertTrue(submit.call_args.args[6])

    def test_demo_kind_is_validated_before_paths_are_selected(self):
        token = self.client.get("/api/status").json()["token"]
        response = self.client.post("/api/demo", headers={"X-Muzhun-Token": token}, json={"kind": "../../private"})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
