import re
from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field, model_validator
from ..config import Config
from .fields import FieldEvaluation


DOCUMENT_DATA_FIELDS = {
    "AADHAAR_CARD": "aadhaar_data",
    "PAN_CARD": "pan_data",
    "DRIVING_LICENCE": "driving_licence_data",
    "PASSPORT": "passport_data",
    "NACH_MANDATE": "nach_mandate_data",
    "FATCA_ANNEXURE": "fatca_annexure_data",
    "BENEFIT_ILLUSTRATION": "benefit_illustration_data",
    "MORAL_HAZARD_QUESTIONNAIRE": "moral_hazard_data",
    "MULTIPLE_POLICIES_CONSENT": "multiple_policies_data",
    "SUITABILITY_PROFILER": "suitability_profiler_data",
}

# Core target model schemas mapped precisely to requested fields
class AadhaarFields(BaseModel):
    aadhaar_number: FieldEvaluation
    full_name: FieldEvaluation
    date_of_birth: FieldEvaluation
    address: FieldEvaluation

class PanFields(BaseModel):
    pan_number: FieldEvaluation
    full_name: FieldEvaluation
    father_name: FieldEvaluation
    date_of_birth: FieldEvaluation

class DrivingLicenceFields(BaseModel):
    dl_number: FieldEvaluation
    name: FieldEvaluation
    date_of_issue: FieldEvaluation
    valid_till_date: FieldEvaluation

class PassportFields(BaseModel):
    passport_number: FieldEvaluation
    date_of_birth: FieldEvaluation
    date_of_expiry: FieldEvaluation
    mrz_line_2: FieldEvaluation

class NachMandateFields(BaseModel):
    bank_account_number: FieldEvaluation
    ifsc_code: FieldEvaluation
    bank_name: FieldEvaluation
    amount_figures: FieldEvaluation
    frequency: FieldEvaluation

class FatcaAnnexureFields(BaseModel):
    policy_number: FieldEvaluation
    tin_or_pan: FieldEvaluation
    father_name: FieldEvaluation
    place_of_birth: FieldEvaluation
    nationality: FieldEvaluation

class BenefitIllustrationFields(BaseModel):
    application_number: FieldEvaluation
    policyholder_name: FieldEvaluation
    date: FieldEvaluation
    place: FieldEvaluation

class MoralHazardFields(BaseModel):
    application_number: FieldEvaluation
    name_of_life_assured: FieldEvaluation
    nominee_relationship: FieldEvaluation
    date: FieldEvaluation
    place: FieldEvaluation

class MultiplePoliciesFields(BaseModel):
    proposer_name: FieldEvaluation
    reason_for_multiple_policies: FieldEvaluation = Field(..., description="Checkbox selection evaluation analysis.")
    date: FieldEvaluation
    place: FieldEvaluation

class SuitabilityProfilerFields(BaseModel):
    application_number: FieldEvaluation
    name_of_life_assured: FieldEvaluation
    name_of_agent_sp: FieldEvaluation
    date: FieldEvaluation
    place: FieldEvaluation

class MasterDocumentIntelligencePayload(BaseModel):
    """Top-level orchestrated parsing structure for real-time document compliance checking."""
    document_type: Literal[
        "AADHAAR_CARD",
        "PAN_CARD",
        "DRIVING_LICENCE",
        "PASSPORT",
        "NACH_MANDATE",
        "FATCA_ANNEXURE",
        "BENEFIT_ILLUSTRATION",
        "MORAL_HAZARD_QUESTIONNAIRE",
        "MULTIPLE_POLICIES_CONSENT",
        "SUITABILITY_PROFILER",
    ]
    text_medium: str = Field(..., description="Medium layout condition checks: PRINTED, HANDWRITTEN, or MIXED")
    
    # Polymorphic optional targets
    aadhaar_data: Optional[AadhaarFields] = None
    pan_data: Optional[PanFields] = None
    driving_licence_data: Optional[DrivingLicenceFields] = None
    passport_data: Optional[PassportFields] = None
    nach_mandate_data: Optional[NachMandateFields] = None
    fatca_annexure_data: Optional[FatcaAnnexureFields] = None
    benefit_illustration_data: Optional[BenefitIllustrationFields] = None
    moral_hazard_data: Optional[MoralHazardFields] = None
    multiple_policies_data: Optional[MultiplePoliciesFields] = None
    suitability_profiler_data: Optional[SuitabilityProfilerFields] = None
    
    system_evaluation_matrix: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def run_production_evaluation_matrix(self) -> "MasterDocumentIntelligencePayload":
        failures: List[str] = []
        scores: List[float] = []
        
        target_attr = DOCUMENT_DATA_FIELDS[self.document_type]
        data_block = getattr(self, target_attr, None)
        
        if not data_block:
            model_type = {
                "AADHAAR_CARD": AadhaarFields,
                "PAN_CARD": PanFields,
                "DRIVING_LICENCE": DrivingLicenceFields,
                "PASSPORT": PassportFields,
                "NACH_MANDATE": NachMandateFields,
                "FATCA_ANNEXURE": FatcaAnnexureFields,
                "BENEFIT_ILLUSTRATION": BenefitIllustrationFields,
                "MORAL_HAZARD_QUESTIONNAIRE": MoralHazardFields,
                "MULTIPLE_POLICIES_CONSENT": MultiplePoliciesFields,
                "SUITABILITY_PROFILER": SuitabilityProfilerFields,
            }[self.document_type]
            self.system_evaluation_matrix = {
                "aggregate_confidence_score": 0.0,
                "validation_failures": ["TARGET_DATA_BLOCK_NOT_POPULATED"],
                "final_routing_decision": "HUMAN_REVIEWS_REQUIRED",
                "review_threshold": Config.FIELD_CONFIDENCE_THRESHOLD,
                "review_threshold_rationale": Config.FIELD_CONFIDENCE_THRESHOLD_RATIONALE,
                "flagged_fields": [
                    {
                        "field": field_name,
                        "confidence": 0.0,
                        "reason": "FIELD_NOT_EXTRACTED",
                    }
                    for field_name in model_type.model_fields
                ],
            }
            return self

        flagged_fields: List[Dict[str, Any]] = []
        for field_name in type(data_block).model_fields:
            field_obj = getattr(data_block, field_name)
            if not isinstance(field_obj, FieldEvaluation):
                continue

            reasons = []
            if field_obj.value and len(str(field_obj.value).strip()) > 0:
                field_obj.null_check = True
                clean_val = (
                    str(field_obj.value)
                    .replace(" ", "")
                    .replace("-", "")
                    .upper()
                )

                # Format validations
                if field_name == "pan_number":
                    field_obj.regex_match = bool(re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$", clean_val))
                elif field_name == "aadhaar_number":
                    field_obj.regex_match = bool(re.match(r"^[0-9]{12}$", clean_val))
                elif field_name == "ifsc_code":
                    field_obj.regex_match = bool(re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", clean_val))
                else:
                    field_obj.regex_match = True

                if not field_obj.regex_match:
                    failures.append(f"{field_name.upper()}_PATTERN_COMPLIANCE_ERROR")
                    reasons.append("FORMAT_VALIDATION_FAILED")
            else:
                failures.append(f"{field_name.upper()}_IS_EMPTY_OR_NULL")

                field_obj.null_check = False
                field_obj.regex_match = False
                reasons.append("FIELD_NOT_EXTRACTED")

            field_obj.final_field_score = (
                max(
                    0.0,
                    field_obj.ai_confidence
                    - (
                        Config.HANDWRITTEN_PENALTY
                        if field_obj.is_handwritten
                        else 0.0
                    ),
                )
                if field_obj.null_check
                else 0.0
            )
            if field_obj.null_check and not field_obj.regex_match:
                field_obj.final_field_score = min(
                    field_obj.final_field_score,
                    Config.FIELD_CONFIDENCE_THRESHOLD - 0.01,
                )
            field_obj.requires_human_review = (
                field_obj.final_field_score < Config.FIELD_CONFIDENCE_THRESHOLD
                or not field_obj.null_check
                or not field_obj.regex_match
            )
            scores.append(field_obj.final_field_score)

            if field_obj.final_field_score < Config.FIELD_CONFIDENCE_THRESHOLD:
                reasons.append("BELOW_CONFIDENCE_THRESHOLD")
            if field_obj.requires_human_review:
                flagged_fields.append(
                    {
                        "field": field_name,
                        "value": field_obj.value,
                        "confidence": round(field_obj.final_field_score, 3),
                        "reason": ", ".join(dict.fromkeys(reasons)),
                    }
                )

        avg_confidence = sum(scores) / len(scores) if scores else 0.0
        is_automated = (
            avg_confidence >= Config.MIN_AUTOMATION_THRESHOLD
            and not failures
            and not flagged_fields
        )
        route = "AUTOMATED_PROCESSING" if is_automated else "HUMAN_REVIEWS_REQUIRED"
        
        self.system_evaluation_matrix = {
            "aggregate_confidence_score": round(avg_confidence, 2),
            "validation_failures": failures,
            "final_routing_decision": route,
            "handwritten_risk_detected": self.text_medium in ["HANDWRITTEN", "MIXED"],
            "review_threshold": Config.FIELD_CONFIDENCE_THRESHOLD,
            "review_threshold_rationale": Config.FIELD_CONFIDENCE_THRESHOLD_RATIONALE,
            "flagged_fields": flagged_fields,
        }
        return self
