from typing import Dict, Any
from ..schemas.documents import DOCUMENT_DATA_FIELDS
from ..utils.evaluator import StageGateEvaluator, CompleteMultiStageEvaluation

class GatedDocumentProcessor:
    """Runs a step-by-step validation pipeline that tracks errors at every gate."""
    def __init__(self):
        self.evaluator = StageGateEvaluator()

    def process_and_evaluate_stages(self, live_extraction: Dict[str, Any], ground_truth: Dict[str, Any]) -> CompleteMultiStageEvaluation:
        # Step 1: Evaluate Classification Gate
        class_metrics = self.evaluator.evaluate_classification_step(
            predicted_type=live_extraction.get("document_type", ""),
            ground_truth_type=ground_truth.get("document_type", ""),
            ai_confidence=live_extraction.get("classification_confidence", 0.0)
        )

        # Step 2: Evaluate OCR Layout Gate
        ocr_metrics = self.evaluator.evaluate_ocr_layout_step(
            raw_ocr_text=live_extraction.get("raw_ocr_dump", ""),
            ground_truth_text=ground_truth.get("raw_text_ground_truth", "")
        )

        # Step 3: Evaluate Target Field Extraction Gate
        document_type = live_extraction.get("document_type", "").upper()
        pred_data_key = DOCUMENT_DATA_FIELDS.get(document_type, "")
        pred_fields = live_extraction.get(pred_data_key, {})
        gt_fields = ground_truth.get("extracted_fields", {})

        field_metrics = self.evaluator.evaluate_field_validation_step(gt_fields, pred_fields)

        # Global Route Gate Resolution Logic
        if class_metrics.passed_gate and ocr_metrics.passed_gate and field_metrics.passed_gate:
            final_route = "AUTOMATED_STRAIGHT_THROUGH_PROCESSING"
        else:
            final_route = "HUMAN_OPERATIONS_MANUAL_REVIEW"

        return CompleteMultiStageEvaluation(
            classification_stage=class_metrics,
            ocr_layout_stage=ocr_metrics,
            field_validation_stage=field_metrics,
            overall_routing_decision=final_route
        )
