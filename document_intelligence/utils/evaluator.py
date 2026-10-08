from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

class StepMetrics(BaseModel):
    """Evaluation status metrics for a single pipeline stage."""
    passed_gate: bool
    confidence_score: float
    error_message: Optional[str] = None
    stage_metadata: Dict[str, Any] = Field(default_factory=dict)

class CompleteMultiStageEvaluation(BaseModel):
    """The master evaluation dashboard encompassing all system steps."""
    classification_stage: StepMetrics
    ocr_layout_stage: StepMetrics
    field_validation_stage: StepMetrics
    overall_routing_decision: str

class StageGateEvaluator:
    """Performs isolated, step-by-step quality evaluations during runtime."""

    @staticmethod
    def _distance(reference: str, hypothesis: str) -> int:
        if len(reference) < len(hypothesis):
            reference, hypothesis = hypothesis, reference
        previous = list(range(len(hypothesis) + 1))
        for row, reference_char in enumerate(reference, start=1):
            current = [row]
            for column, hypothesis_char in enumerate(hypothesis, start=1):
                current.append(
                    min(
                        current[column - 1] + 1,
                        previous[column] + 1,
                        previous[column - 1]
                        + (reference_char != hypothesis_char),
                    )
                )
            previous = current
        return previous[-1]

    @staticmethod
    def calculate_cer(reference: str, hypothesis: str) -> float:
        ref, hyp = (reference or "").strip().lower(), (hypothesis or "").strip().lower()
        if not ref and not hyp: return 0.0
        if not ref: return 1.0
        return min(1.0, StageGateEvaluator._distance(ref, hyp) / len(ref))

    def evaluate_classification_step(self, predicted_type: str, ground_truth_type: str, ai_confidence: float) -> StepMetrics:
        """STAGE 1: Validates if the document classifier accurately matched target classes."""
        is_correct = (predicted_type == ground_truth_type) and (predicted_type != "UNKNOWN")
        passed = is_correct and (ai_confidence >= 0.80)

        return StepMetrics(
            passed_gate=passed,
            confidence_score=ai_confidence,
            error_message=None if passed else f"Classification failed. Expected: {ground_truth_type}, Got: {predicted_type}",
            stage_metadata={"match_success": is_correct}
        )

    def evaluate_ocr_layout_step(self, raw_ocr_text: str, ground_truth_text: str) -> StepMetrics:
        """STAGE 2: Evaluates raw OCR/VLM text recovery before structured mapping."""
        if not raw_ocr_text or not ground_truth_text:
            return StepMetrics(passed_gate=False, confidence_score=0.0, error_message="Empty textual content fields encountered.")

        # Determine global structural text mismatch via CER
        layout_cer = self.calculate_cer(ground_truth_text, raw_ocr_text)
        text_accuracy = 1.0 - layout_cer
        passed = text_accuracy >= 0.75  # OCR layout quality gate threshold

        return StepMetrics(
            passed_gate=passed,
            confidence_score=round(text_accuracy, 4),
            error_message=None if passed else f"High text distortion rate (CER: {round(layout_cer, 2)}). Messy handwriting suspected.",
            stage_metadata={"character_error_rate": round(layout_cer, 4)}
        )

    def evaluate_field_validation_step(self, gt_fields: Dict[str, str], pred_fields: Dict[str, Any]) -> StepMetrics:
        """STAGE 3: Validates individual target business rules and values."""
        true_positives = 0
        total_fields = len(gt_fields)
        cer_accumulator = 0.0
        failures = []

        for field_name, gt_val in gt_fields.items():
            pred_obj = pred_fields.get(field_name, {})
            # Handle both raw strings and structured dict field types
            pred_val = str(pred_obj.get("value", "") if isinstance(pred_obj, dict) else pred_obj).strip()

            cer = self.calculate_cer(gt_val, pred_val)
            cer_accumulator += cer

            if cer < 0.15:  # Exact field matching logic
                true_positives += 1
            else:
                failures.append(f"{field_name.upper()}_DATA_MISMATCH")

        avg_cer = cer_accumulator / total_fields if total_fields > 0 else 1.0
        accuracy = true_positives / total_fields if total_fields > 0 else 0.0
        passed = (accuracy >= 0.90) and (len(failures) == 0)

        return StepMetrics(
            passed_gate=passed,
            confidence_score=round(accuracy, 4),
            error_message=None if passed else f"Field checks failed metrics profiles: {failures}",
            stage_metadata={"average_field_cer": round(avg_cer, 4), "failed_keys": failures}
        )
