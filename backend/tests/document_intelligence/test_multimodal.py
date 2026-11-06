from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from document_intelligence.core.pipeline import process_uploads
from document_intelligence.utils.ocr import MultimodalOCRProcessor


def candidate(confidence=0.99):
    return {
        "document_type": "PAN_CARD",
        "text_medium": "PRINTED",
        "classification_confidence": confidence,
        "fields": {
            name: {"value": value, "is_handwritten": False, "ai_confidence": confidence}
            for name, value in {
                "pan_number": "ABCDE1234F", "full_name": "Alex Example",
                "father_name": "Morgan Example", "date_of_birth": "1990-01-02",
            }.items()
        },
    }


def processor(primary, retry=None):
    instance = MultimodalOCRProcessor.__new__(MultimodalOCRProcessor)
    instance._extract_from_image = Mock(return_value=deepcopy(primary))
    instance._extract_with_ocr = Mock(return_value=deepcopy(retry))
    return instance


def test_high_quality_image_extraction_skips_ocr():
    instance = processor(candidate())
    events = []
    result = instance.classify_and_extract_page(b"image", "image/png", events.append)
    assert result["extraction_method"] == "multimodal"
    assert result["ocr_status"] == "SKIPPED"
    instance._extract_with_ocr.assert_not_called()
    assert any(event.get("status") == "skipped" for event in events)


@pytest.mark.parametrize("problem", ["low_confidence", "missing", "invalid_format", "handwritten", "low_classification"])
def test_uncertain_image_result_gets_one_ocr_retry(problem):
    initial = candidate()
    field = initial["fields"]["pan_number"]
    if problem == "low_confidence":
        field["ai_confidence"] = 0.5
    if problem == "missing":
        field["value"] = None
    if problem == "invalid_format":
        field["value"] = "INVALID"
    if problem == "handwritten":
        field["is_handwritten"] = True
    if problem == "low_classification":
        initial["classification_confidence"] = 0.5
    instance = processor(initial, candidate())
    result = instance.classify_and_extract_page(b"image", "image/png")
    instance._extract_with_ocr.assert_called_once()
    assert result["extraction_method"] == "ocr_assisted"
    assert len(result["extraction_attempts"]) == 2


def test_primary_api_failure_uses_ocr_retry():
    instance = processor(None, candidate())
    instance._extract_from_image.side_effect = RuntimeError("provider unavailable")
    result = instance.classify_and_extract_page(b"image", "image/png")
    assert result["extraction_method"] == "ocr_assisted"
    assert result["extraction_attempts"][0]["error_type"] == "RuntimeError"


def test_failed_retry_keeps_primary_for_review():
    instance = processor(candidate(0.5))
    instance._extract_with_ocr.side_effect = RuntimeError("OCR unavailable")
    result = instance.classify_and_extract_page(b"image", "image/png")
    assert result["extraction_method"] == "multimodal"
    assert result["ocr_status"] == "FAILED"
    assert result["extraction_attempts"][-1]["status"] == "failed"


def test_both_attempts_fail_without_a_false_success():
    instance = processor(None)
    instance._extract_from_image.side_effect = RuntimeError("primary failed")
    instance._extract_with_ocr.side_effect = RuntimeError("retry failed")
    result = instance.classify_and_extract_page(b"image", "image/png")
    assert result["document_type"] == "UNKNOWN"
    assert result["ocr_status"] == "FAILED"
    assert len(result["extraction_attempts"]) == 2


def test_conflicting_attempts_are_routed_to_human_review():
    initial = candidate(0.5)
    retry = candidate()
    retry["fields"]["pan_number"]["value"] = "ABCDE1235F"
    instance = processor(initial, retry)
    with tempfile.TemporaryDirectory() as directory:
        result = process_uploads([("sample.png", b"image")], processor_factory=lambda: instance, output_root=Path(directory))
    document = result["documents"][0]
    assert document["retry_conflicts"] == ["pan_number"]
    assert result["review_report"]["human_review_required"]
    assert any(flag["reason"] == "EXTRACTION_ATTEMPTS_DISAGREE" for flag in result["review_report"]["flagged_fields"])
    assert len(document["extraction_attempts"]) == 2


def test_direct_model_request_contains_the_document_image():
    instance = MultimodalOCRProcessor.__new__(MultimodalOCRProcessor)
    instance.clients = []
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"document_type":"UNKNOWN"}'))])
    with patch("document_intelligence.utils.ocr.create_completion_with_fallback", return_value=response) as call:
        instance._extract_from_image(b"image", "image/png")
    parts = call.call_args.kwargs["messages"][0]["content"]
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_conflicting_document_types_require_review():
    retry = {
        "document_type": "BENEFIT_ILLUSTRATION", "text_medium": "PRINTED",
        "classification_confidence": 0.99,
        "fields": {
            name: {"value": value, "ai_confidence": 0.99, "is_handwritten": False}
            for name, value in {"application_number": "TEST-001", "policyholder_name": "Alex Example", "date": "2026-11-06", "place": "Example City"}.items()
        },
    }
    instance = processor(candidate(0.5), retry)
    with tempfile.TemporaryDirectory() as directory:
        result = process_uploads([("sample.png", b"image")], processor_factory=lambda: instance, output_root=directory)
    assert result["documents"][0]["retry_conflicts"] == ["document_type"]
    assert result["review_report"]["human_review_required"]


def test_continuation_page_preserves_retry_review_flags():
    first = candidate()
    first.update(document_reference="DOC-123", is_continuation=False)
    second = candidate(0.5)
    second.update(document_reference="DOC-123", is_continuation=True)
    retry = candidate()
    retry.update(document_reference="DOC-123", is_continuation=True)
    retry["fields"]["pan_number"]["value"] = "ABCDE1235F"
    instance = processor(first, retry)
    instance._extract_from_image.side_effect = [first, second]
    with tempfile.TemporaryDirectory() as directory:
        result = process_uploads([("one.png", b"image"), ("two.png", b"image")], processor_factory=lambda: instance, output_root=directory)
    assert result["document_count"] == 1
    assert result["review_report"]["human_review_required"]
    assert len(result["documents"][0]["extraction_attempts"]) == 3
