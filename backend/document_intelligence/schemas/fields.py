import math
from typing import Any, Optional
from pydantic import BaseModel, Field


def normalize_field(raw_field: Any, handwritten_default: bool) -> dict[str, Any]:
    if not isinstance(raw_field, dict):
        raw_field = {}
    value = raw_field.get("value")
    try:
        confidence = float(raw_field.get("ai_confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    return {
        "value": None if value is None else str(value).strip() or None,
        "is_handwritten": raw_field.get("is_handwritten") if isinstance(raw_field.get("is_handwritten"), bool) else handwritten_default,
        "ai_confidence": min(1.0, max(0.0, confidence)),
    }

class FieldEvaluation(BaseModel):
    """Encapsulates extracted text values alongside validation matrix parameters."""
    value: Optional[str] = Field(None, description="The extracted text or array selection option value.")
    is_handwritten: bool = Field(..., description="True if target text coordinates exhibit handwritten features.")
    ai_confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="VLM-reported confidence score from 0.0 to 1.0.",
    )
    regex_match: bool = Field(False, description="Programmatically set: Confirms layout pattern matching.")
    null_check: bool = Field(False, description="Programmatically set: Checks for field content presence.")
    final_field_score: float = Field(0.0, description="Calculated final field evaluation score.")
    requires_human_review: bool = Field(
        False,
        description="True when field confidence is below the configured threshold.",
    )
