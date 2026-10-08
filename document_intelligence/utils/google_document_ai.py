import logging
from dataclasses import dataclass
from typing import Any

from datapilot.config import get_config, validate_document_ai_config

logger = logging.getLogger("datapilot.google_document_ai")


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float | None


class GoogleDocumentAIProcessor:
    """Extract page text using the configured Google Cloud Document AI processor."""

    def __init__(self, client: Any | None = None):
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client

        validate_document_ai_config()
        settings = get_config()
        try:
            from google.api_core.client_options import ClientOptions
            from google.cloud import documentai
            from google.oauth2 import service_account
        except ImportError as error:
            raise RuntimeError(
                "Google Cloud Document AI support requires "
                "google-cloud-documentai. Install project requirements."
            ) from error

        endpoint = (
            "documentai.googleapis.com"
            if settings.gcp_location.lower() == "us"
            else f"{settings.gcp_location}-documentai.googleapis.com"
        )
        client_options = ClientOptions(api_endpoint=endpoint)
        credentials = None
        if settings.google_application_credentials:
            try:
                credentials = service_account.Credentials.from_service_account_file(
                    settings.google_application_credentials
                )
            except (OSError, ValueError) as error:
                raise RuntimeError(
                    "Could not load the configured Google service-account file. "
                    "Check GOOGLE_APPLICATION_CREDENTIALS."
                ) from error

        self._client = documentai.DocumentProcessorServiceClient(
            client_options=client_options,
            credentials=credentials,
        )
        return self._client

    def process(self, content: bytes, mime_type: str) -> OCRResult:
        validate_document_ai_config()
        settings = get_config()
        try:
            from google.cloud import documentai
        except ImportError as error:
            raise RuntimeError(
                "Google Cloud Document AI support requires "
                "google-cloud-documentai. Install project requirements."
            ) from error

        client = self._get_client()
        name = client.processor_path(
            settings.gcp_project_id,
            settings.gcp_location,
            settings.docai_processor_id,
        )
        raw_document = documentai.RawDocument(
            content=content,
            mime_type=mime_type,
        )
        try:
            response = client.process_document(
                request={
                    "name": name,
                    "raw_document": raw_document,
                }
            )
        except Exception:
            logger.exception("Google Document AI processing request failed")
            raise

        document = response.document
        confidences = [
            token.layout.confidence
            for page in document.pages
            for token in page.tokens
            if getattr(token, "layout", None) is not None
            and getattr(token.layout, "confidence", None) is not None
        ]
        confidence = sum(confidences) / len(confidences) if confidences else None
        return OCRResult(
            text=document.text or "",
            confidence=confidence,
        )
