import json
import tempfile
import unittest
from pathlib import Path

import pymupdf

from document_intelligence.core.pipeline import process_uploads, segment_upload


def pan_response(
    is_continuation=False,
    confidence=0.99,
    pan_number="ABCDE1234F",
):
    return {
        "document_type": "PAN_CARD",
        "classification_confidence": confidence,
        "ocr_confidence": 0.91,
        "text_medium": "PRINTED",
        "document_reference": "DOC-123",
        "is_continuation": is_continuation,
        "fields": {
            "pan_number": {
                "value": pan_number,
                "is_handwritten": False,
                "ai_confidence": 0.99,
            },
            "full_name": {
                "value": "Ravi Kumar",
                "is_handwritten": False,
                "ai_confidence": 0.99,
            },
            "father_name": {
                "value": "Suresh Kumar",
                "is_handwritten": False,
                "ai_confidence": 0.99,
            },
            "date_of_birth": {
                "value": "1990-01-02",
                "is_handwritten": False,
                "ai_confidence": 0.99,
            },
        },
    }


class FakePageProcessor:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def classify_and_extract_page(self, image_bytes, mime_type):
        self.calls.append((image_bytes, mime_type))
        result = next(self.responses)
        if isinstance(result, Exception):
            raise result
        return result


class DocumentSegmentationTests(unittest.TestCase):
    def test_image_upload_becomes_one_isolated_page(self):
        pages = segment_upload("scan.png", b"\x89PNG\r\n\x1a\nscan")

        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].source_file, "scan.png")
        self.assertEqual(pages[0].page_number, 1)
        self.assertEqual(pages[0].mime_type, "image/png")

    def test_pdf_is_segmented_into_ordered_pages(self):
        pdf = pymupdf.open()
        pdf.new_page()
        pdf.new_page()
        pdf_bytes = pdf.tobytes()
        pdf.close()

        pages = segment_upload("multi.pdf", pdf_bytes)

        self.assertEqual([page.page_number for page in pages], [1, 2])
        self.assertEqual([page.mime_type for page in pages], ["image/png", "image/png"])

    def test_invalid_file_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "only PDF"):
            segment_upload("scan.bmp", b"scan")


class DocumentPipelineTests(unittest.TestCase):
    def test_related_pages_group_only_when_reference_and_continuation_match(self):
        processor = FakePageProcessor(
            [
                pan_response(),
                pan_response(is_continuation=True, pan_number=None),
                pan_response(is_continuation=False),
            ]
        )
        with tempfile.TemporaryDirectory() as output_directory:
            result = process_uploads(
                [
                    ("front.png", b"\x89PNG\r\n\x1a\nfront"),
                    ("back.png", b"\x89PNG\r\n\x1a\nback"),
                    ("other.png", b"\x89PNG\r\n\x1a\nother"),
                ],
                processor_factory=lambda: processor,
                output_root=output_directory,
            )

            self.assertEqual(result["page_count"], 3)
            self.assertEqual(result["document_count"], 2)
            grouped, separate = result["documents"]
            self.assertEqual(grouped["source_files"], ["front.png", "back.png"])
            self.assertEqual(grouped["pages"], [1, 1])
            self.assertEqual(
                grouped["extraction"]["pan_data"]["pan_number"]["value"],
                "ABCDE1234F",
            )
            self.assertEqual(separate["source_files"], ["other.png"])
            self.assertEqual(
                grouped["processor_route"],
                "GOOGLE_ID_PROCESSOR",
            )
            self.assertEqual(grouped["ocr_confidence"], 0.91)
            self.assertIn(
                "DOCUMENT_AI_OCR",
                [stage["stage"] for stage in grouped["stage_trace"]],
            )
            self.assertTrue(Path(result["outputs"]["documents_json"]).is_file())
            self.assertTrue(Path(result["outputs"]["review_report_json"]).is_file())
            self.assertTrue(Path(result["outputs"]["excel"]).is_file())

            saved_documents = json.loads(
                Path(result["outputs"]["documents_json"]).read_text(encoding="utf-8")
            )
            self.assertEqual(len(saved_documents), 2)

    def test_invalid_confidence_and_fields_route_to_human_review(self):
        response = pan_response(confidence=0.2, pan_number="NOT-A-PAN")
        processor = FakePageProcessor([response])
        with tempfile.TemporaryDirectory() as output_directory:
            result = process_uploads(
                [("scan.jpg", b"\xff\xd8\xffscan")],
                processor_factory=lambda: processor,
                output_root=output_directory,
            )

        document = result["documents"][0]
        self.assertEqual(
            document["extraction"]["system_evaluation_matrix"][
                "final_routing_decision"
            ],
            "HUMAN_REVIEWS_REQUIRED",
        )
        self.assertEqual(
            document["processor_route"],
            "GOOGLE_ID_PROCESSOR",
        )
        self.assertTrue(result["review_report"]["human_review_required"])
        self.assertTrue(
            any(
                item["field"] == "document_type"
                for item in result["review_report"]["flagged_fields"]
            )
        )

    def test_classification_failure_is_saved_as_review_item(self):
        processor = FakePageProcessor([RuntimeError("mock provider failure")])
        with tempfile.TemporaryDirectory() as output_directory:
            result = process_uploads(
                [("scan.jpg", b"\xff\xd8\xffscan")],
                processor_factory=lambda: processor,
                output_root=output_directory,
            )

        self.assertEqual(result["documents"][0]["document_type"], "UNKNOWN")
        self.assertIn("mock provider failure", result["documents"][0]["error"])
        self.assertTrue(result["review_report"]["human_review_required"])

    def test_progress_callback_receives_boundary_events(self):
        processor = FakePageProcessor([pan_response()])
        events = []
        with tempfile.TemporaryDirectory() as output_directory:
            result = process_uploads(
                [("scan.jpg", b"\xff\xd8\xffscan")],
                processor_factory=lambda: processor,
                output_root=output_directory,
                progress_callback=events.append,
            )

        stages = [e.get("stage") for e in events]
        self.assertIn("segmentation", stages)
        self.assertIn("page_start", stages)
        self.assertIn("ocr", stages)
        self.assertIn("classification", stages)
        self.assertIn("validation", stages)
        self.assertIn("confidence_shield", stages)
        self.assertIn("grouping", stages)
        self.assertIn("review", stages)
        self.assertIn("export", stages)


if __name__ == "__main__":
    unittest.main()
