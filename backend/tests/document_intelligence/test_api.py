import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from document_intelligence import api
from main import app


class DocumentIntelligenceApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_process_requires_explicit_external_processing_consent(self):
        with patch.object(api, "process_uploads") as process_uploads:
            response = self.client.post(
                "/api/documents/process",
                files=[("files", ("sample.png", b"sample", "image/png"))],
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Explicit consent", response.json()["detail"])
        process_uploads.assert_not_called()

    def test_consent_allows_upload_pipeline_and_returns_download_links(self):
        result = {
            "job_id": "a" * 32,
            "document_count": 1,
            "page_count": 1,
            "threshold": 0.85,
            "review_report": {"flagged_fields": []},
            "documents": [],
            "outputs": {},
        }
        with patch.object(api, "process_uploads", return_value=result) as process_uploads:
            response = self.client.post(
                "/api/documents/process",
                data={"external_processing_consent": "true"},
                files=[("files", ("sample.png", b"sample", "image/png"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["outputs"]["documents_json"],
            f"/api/documents/{'a' * 32}/documents.json",
        )
        self.assertEqual(process_uploads.call_args.args[0][0][0], "sample.png")

    def test_result_download_is_limited_to_known_job_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            job_directory = Path(temporary_directory) / ("b" * 32)
            job_directory.mkdir()
            (job_directory / "documents.json").write_text(
                json.dumps([{"document_type": "PAN_CARD"}]),
                encoding="utf-8",
            )
            with patch.object(api, "OUTPUT_DIRECTORY", Path(temporary_directory)):
                response = self.client.get(
                    f"/api/documents/{'b' * 32}/documents.json"
                )
                traversal = self.client.get(
                    f"/api/documents/{'b' * 32}/../../secrets.txt"
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["document_type"], "PAN_CARD")
        self.assertEqual(traversal.status_code, 404)

    def test_process_stream_requires_explicit_consent(self):
        with patch.object(api, "process_uploads") as process_uploads:
            response = self.client.post(
                "/api/documents/process/stream",
                files=[("files", ("sample.png", b"sample", "image/png"))],
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Explicit consent", response.json()["detail"])
        process_uploads.assert_not_called()

    def test_process_stream_streams_progress_and_complete_events(self):
        result = {
            "job_id": "c" * 32,
            "document_count": 1,
            "page_count": 1,
            "threshold": 0.85,
            "review_report": {"flagged_fields": []},
            "documents": [{"document_type": "PAN_CARD"}],
            "outputs": {},
        }

        def mock_process(files, progress_callback=None, **kwargs):
            if progress_callback:
                progress_callback({"stage": "segmentation", "status": "completed", "message": "Segmented 1 page"})
                progress_callback({"stage": "ocr", "status": "completed", "message": "OCR done"})
            return result

        with patch.object(api, "process_uploads", side_effect=mock_process):
            response = self.client.post(
                "/api/documents/process/stream",
                data={"external_processing_consent": "true"},
                files=[("files", ("sample.png", b"sample", "image/png"))],
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))
        events = [
            json.loads(line[5:].strip())
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]
        types = [e.get("type") for e in events]
        self.assertIn("progress", types)
        self.assertIn("complete", types)
        complete_event = next(e for e in events if e.get("type") == "complete")
        self.assertEqual(
            complete_event["result"]["outputs"]["documents_json"],
            f"/api/documents/{'c' * 32}/documents.json",
        )


if __name__ == "__main__":
    unittest.main()
