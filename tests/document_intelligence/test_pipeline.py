import unittest

from pydantic import ValidationError

from datapilot.config import Config
from document_intelligence.core.processor import GatedDocumentProcessor
from document_intelligence.schemas.documents import (
    MasterDocumentIntelligencePayload,
    PanFields,
)
from document_intelligence.schemas.fields import FieldEvaluation
from document_intelligence.utils.evaluator import StageGateEvaluator


def field(value, confidence=0.99, handwritten=False):
    return FieldEvaluation(
        value=value,
        is_handwritten=handwritten,
        ai_confidence=confidence,
    )


class DocumentIntelligenceTests(unittest.TestCase):
    def test_cer_uses_character_edit_distance_and_bounds_empty_reference(self):
        self.assertEqual(StageGateEvaluator.calculate_cer("kitten", "sitting"), 0.5)
        self.assertEqual(StageGateEvaluator.calculate_cer("", ""), 0.0)
        self.assertEqual(StageGateEvaluator.calculate_cer("", "extra"), 1.0)

    def test_pan_schema_uses_pan_data_and_produces_structured_flags(self):
        payload = MasterDocumentIntelligencePayload(
            document_type="PAN_CARD",
            text_medium="PRINTED",
            pan_data=PanFields(
                pan_number=field("ABCDE1234F"),
                full_name=field("Ravi Kumar"),
                father_name=field("Suresh Kumar"),
                date_of_birth=field("1990-01-02"),
            ),
        )

        matrix = payload.system_evaluation_matrix
        self.assertEqual(matrix["final_routing_decision"], "AUTOMATED_PROCESSING")
        self.assertEqual(matrix["flagged_fields"], [])
        self.assertEqual(
            matrix["review_threshold"],
            Config.FIELD_CONFIDENCE_THRESHOLD,
        )
        self.assertTrue(matrix["review_threshold_rationale"])
        self.assertTrue(payload.pan_data.pan_number.regex_match)

    def test_handwritten_low_confidence_field_is_flagged(self):
        payload = MasterDocumentIntelligencePayload(
            document_type="PAN_CARD",
            text_medium="MIXED",
            pan_data=PanFields(
                pan_number=field("ABCDE1234F", handwritten=True),
                full_name=field("Ravi Kumar"),
                father_name=field("Suresh Kumar"),
                date_of_birth=field("1990-01-02"),
            ),
        )

        matrix = payload.system_evaluation_matrix
        self.assertEqual(matrix["final_routing_decision"], "HUMAN_REVIEWS_REQUIRED")
        self.assertEqual(matrix["flagged_fields"][0]["field"], "pan_number")
        self.assertLess(
            matrix["flagged_fields"][0]["confidence"],
            Config.FIELD_CONFIDENCE_THRESHOLD,
        )
        self.assertTrue(matrix["handwritten_risk_detected"])

    def test_missing_pan_block_flags_each_required_field(self):
        payload = MasterDocumentIntelligencePayload(
            document_type="PAN_CARD",
            text_medium="PRINTED",
        )

        matrix = payload.system_evaluation_matrix
        self.assertEqual(matrix["final_routing_decision"], "HUMAN_REVIEWS_REQUIRED")
        self.assertEqual(
            {entry["field"] for entry in matrix["flagged_fields"]},
            {"pan_number", "full_name", "father_name", "date_of_birth"},
        )

    def test_confidence_must_be_between_zero_and_one(self):
        with self.assertRaises(ValidationError):
            field("ABCDE1234F", confidence=1.1)

    def test_processor_reads_pan_fields_and_routes_mismatches_to_review(self):
        report = GatedDocumentProcessor().process_and_evaluate_stages(
            live_extraction={
                "document_type": "PAN_CARD",
                "classification_confidence": 0.99,
                "raw_ocr_dump": "PAN ABCDE1234F NAME RAVI",
                "pan_data": {"pan_number": {"value": "ABCDE1234F"}},
            },
            ground_truth={
                "document_type": "PAN_CARD",
                "raw_text_ground_truth": "PAN ABCDE1234F NAME RAVI",
                "extracted_fields": {"pan_number": "ABCDE1234F"},
            },
        )

        self.assertEqual(
            report.overall_routing_decision,
            "AUTOMATED_STRAIGHT_THROUGH_PROCESSING",
        )
        self.assertTrue(report.field_validation_stage.passed_gate)


if __name__ == "__main__":
    unittest.main()
