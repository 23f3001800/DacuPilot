import json
from .core.processor import GatedDocumentProcessor

def run_step_level_benchmark():
    print("[+] Launching Multi-Stage Document Evaluation Telemetry Pipeline...")

    # Simulating a real processing run on a handwritten PAN card
    simulated_live_extraction = {
        "document_type": "PAN_CARD",
        "classification_confidence": 0.94,
        "raw_ocr_dump": "INCOME TAX DEPARTMENT... PERMANENT ACCOUNT NUMBER... NAME: RAJESH K SWAMY... FATHER: M S SWAMY",
        "pan_data": {
            "pan_number": {"value": "ABCDE1234F", "is_handwritten": False},
            "full_name": {"value": "Rajesh K Swamy", "is_handwritten": True}, # Messy handwritten text
            "father_name": {"value": "M S Swamy", "is_handwritten": True}     # Cursive signature mismatch
        }
    }

    # Verified ground truth data
    ground_truth_validation_dataset = {
        "document_type": "PAN_CARD",
        "raw_text_ground_truth": "INCOME TAX DEPARTMENT GOVT OF INDIA PERMANENT ACCOUNT NUMBER ABCDE1234F NAME RAJESH KUMAR SWAMY FATHER MANGALORE SHRINIVAS SWAMY",
        "extracted_fields": {
            "pan_number": "ABCDE1234F",
            "full_name": "Rajesh Kumar Sharma",     # Error: Surname misread by VLM
            "father_name": "Mangalore Shrinivas Swamy" # Error: Initials extracted instead of full name
        }
    }

    processor = GatedDocumentProcessor()
    evaluation_report = processor.process_and_evaluate_stages(
        live_extraction=simulated_live_extraction,
        ground_truth=ground_truth_validation_dataset
    )

    print("\n📊 ================= MULTI-STAGE EVALUATION MATRIX ================= 📊")
    print(f"[Step 1] Classification Gate -> Passed: {evaluation_report.classification_stage.passed_gate} | Score: {evaluation_report.classification_stage.confidence_score * 100}%")
    print(f"[Step 2] OCR Layout Gate     -> Passed: {evaluation_report.ocr_layout_stage.passed_gate} | Text Recovery Acc: {evaluation_report.ocr_layout_stage.confidence_score * 100}%")
    print(f"[Step 3] Field Business Gate -> Passed: {evaluation_report.field_validation_stage.passed_gate} | Match Match Acc: {evaluation_report.field_validation_stage.confidence_score * 100}%")
    print("----------------------------------------------------------------------")
    print(f"[FINAL SYSTEM TARGET ROUTE]  -> {evaluation_report.overall_routing_decision}")
    print("======================================================================\n")

    print("[+] Complete Step-Level Evaluation JSON Telemetry:")
    print(json.dumps(evaluation_report.model_dump(), indent=2))

if __name__ == "__main__":
    run_step_level_benchmark()
