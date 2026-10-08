import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
    API_KEY = os.getenv("GEMINI_API_KEY", "")
    FIELD_CONFIDENCE_THRESHOLD = 0.85
    MIN_AUTOMATION_THRESHOLD = FIELD_CONFIDENCE_THRESHOLD
    HANDWRITTEN_PENALTY = 0.20
    FIELD_CONFIDENCE_THRESHOLD_RATIONALE = (
        "Use a conservative 0.85 threshold because incorrect identity and "
        "financial field values can cause onboarding or payment errors."
    )

    @classmethod
    def validate(cls) -> None:
        cls.API_KEY = os.getenv("GEMINI_API_KEY", cls.API_KEY)
        if not cls.API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is required to run document OCR."
            )



import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Google Cloud Authentication Configurations
    gcp_project_id: str = os.environ.get("GCP_PROJECT_ID", "your-gcp-project-id")
    gcp_location: str = os.environ.get("GCP_LOCATION", "us")  # e.g., 'us' or 'eu'
    
    # Document AI Processor endpoints
    # For a mixed typed/handwritten pipeline, a Form Parser or Custom Classifier/Extractor is used
    docai_processor_id: str = os.environ.get("DOCAI_PROCESSOR_ID", "your-processor-id")
    
    # Absolute confidence boundary threshold for straight-through automation
    confidence_threshold: float = 0.85

    class Config:
        env_file = ".env"

def get_settings() -> Settings:
    return Settings()
