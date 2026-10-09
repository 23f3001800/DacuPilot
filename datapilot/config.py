import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_EXCEL_FILE = (
    Path(__file__).resolve().parents[1]
    / "excel_agent"
    / "Inventory-Records-Sample-Data.xlsx"
)


@dataclass(frozen=True)
class AppConfig:
    ai_primary_provider: str
    gemini_api_key: str = field(repr=False)
    gemini_model: str
    azure_api_key: str = field(repr=False)
    azure_base_url: str
    azure_model: str
    azure_auth_mode: str
    tavily_api_key: str = field(repr=False)
    excel_file_path: str
    gcp_project_id: str
    gcp_location: str
    docai_processor_id: str
    google_application_credentials: str = field(repr=False)
    field_confidence_threshold: float
    handwriting_penalty: float
    log_file: str
    log_level: str
    azure_document_intelligence_endpoint: str = ""
    azure_document_intelligence_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"

    @classmethod
    def from_environment(cls) -> "AppConfig":
        azure_key = (
            os.getenv("AZURE_OPENAI_API_KEY")
            or os.getenv("AZURE_FOUNDRY_API_KEY")
            or ""
        ).strip()
        azure_url = (
            os.getenv("AZURE_OPENAI_BASE_URL")
            or os.getenv("AZURE_FOUNDRY_ENDPOINT")
            or ""
        ).strip()
        azure_model = (
            os.getenv("AZURE_OPENAI_MODEL")
            or os.getenv("AZURE_FOUNDRY_MODEL")
            or ""
        ).strip()
        azure_auth_mode = os.getenv("AZURE_OPENAI_AUTH_MODE", "api-key").strip().lower()
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        openai_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
        openai_model = os.getenv("OPENAI_MODEL", "gpt-4o").strip()
        configured_primary = (
            os.getenv("AI_PRIMARY_PROVIDER")
            or os.getenv("TRACEROOT_PROVIDER")
            or ("openai" if openai_key else "gemini")
        ).strip().lower()

        return cls(
            ai_primary_provider=configured_primary,
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip(),
            azure_api_key=azure_key,
            azure_base_url=azure_url,
            azure_model=azure_model,
            azure_auth_mode=azure_auth_mode,
            openai_api_key=openai_key,
            openai_base_url=openai_url,
            openai_model=openai_model,
            tavily_api_key=os.getenv("TAVILY_API_KEY", "").strip(),
            excel_file_path=os.getenv("EXCEL_FILE_PATH", "").strip(),
            gcp_project_id=os.getenv("GCP_PROJECT_ID", "").strip().strip('"'),
            gcp_location=os.getenv("GCP_LOCATION", "").strip().strip('"'),
            docai_processor_id=os.getenv("DOCAI_PROCESSOR_ID", "").strip().strip('"'),
            google_application_credentials=os.getenv(
                "GOOGLE_APPLICATION_CREDENTIALS", ""
            ).strip().strip('"'),
            field_confidence_threshold=float(
                os.getenv(
                    "FIELD_CONFIDENCE_THRESHOLD",
                    os.getenv("CONFIDENCE_THRESHOLD", "0.85"),
                )
            ),
            handwriting_penalty=float(
                os.getenv("HANDWRITTEN_CONFIDENCE_PENALTY", "0.20")
            ),
            azure_document_intelligence_endpoint=os.getenv(
                "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", ""
            ).strip(),
            azure_document_intelligence_key=os.getenv(
                "AZURE_DOCUMENT_INTELLIGENCE_KEY", ""
            ).strip(),
            log_file=os.getenv("DATAPILOT_LOG_FILE", "agent_server.log").strip(),
            log_level=os.getenv("DATAPILOT_LOG_LEVEL", "INFO").strip().upper(),
        )


def get_config() -> AppConfig:
    return AppConfig.from_environment()


class Config:
    _initial = get_config()
    FIELD_CONFIDENCE_THRESHOLD = _initial.field_confidence_threshold
    MIN_AUTOMATION_THRESHOLD = FIELD_CONFIDENCE_THRESHOLD
    HANDWRITTEN_PENALTY = _initial.handwriting_penalty
    FIELD_CONFIDENCE_THRESHOLD_RATIONALE = (
        "Use a conservative confidence threshold because incorrect identity and "
        "financial field values can cause onboarding or payment errors."
    )

    @classmethod
    def validate(cls) -> None:
        if not 0 <= cls.FIELD_CONFIDENCE_THRESHOLD <= 1:
            raise RuntimeError("FIELD_CONFIDENCE_THRESHOLD must be between 0 and 1.")
        if not 0 <= cls.HANDWRITTEN_PENALTY <= 1:
            raise RuntimeError("HANDWRITTEN_CONFIDENCE_PENALTY must be between 0 and 1.")


def validate_document_ai_config() -> None:
    settings = get_config()
    missing = [
        name
        for name, value in (
            ("GCP_PROJECT_ID", settings.gcp_project_id),
            ("GCP_LOCATION", settings.gcp_location),
            ("DOCAI_PROCESSOR_ID", settings.docai_processor_id),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Google Cloud Document AI is not configured. Set: "
            + ", ".join(missing)
            + "."
        )
