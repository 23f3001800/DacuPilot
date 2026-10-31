from typing import Optional
from pydantic import BaseModel, Field

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
