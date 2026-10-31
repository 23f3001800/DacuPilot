import logging
from typing import Any

from datapilot.config import get_config

from .google_document_ai import OCRResult

logger = logging.getLogger("datapilot.azure_document_ai")


class AzureDocumentAIProcessor:
    """Extract page text using Azure Document Intelligence (Layout model)."""

    def __init__(self, client: Any | None = None):
        self._client = client

    def _get_client(self):
        if self._client is not None:
            return self._client

        settings = get_config()
        if not settings.azure_document_intelligence_endpoint or not settings.azure_document_intelligence_key:
            raise RuntimeError(
                "Azure Document Intelligence is not configured. Set "
                "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and AZURE_DOCUMENT_INTELLIGENCE_KEY."
            )
        try:
            from azure.ai.documentintelligence import DocumentIntelligenceClient
            from azure.core.credentials import AzureKeyCredential
        except ImportError as error:
            raise RuntimeError(
                "Azure Document Intelligence support requires "
                "azure-ai-documentintelligence. Install project requirements."
            ) from error

        self._client = DocumentIntelligenceClient(
            endpoint=settings.azure_document_intelligence_endpoint,
            credential=AzureKeyCredential(settings.azure_document_intelligence_key),
        )
        return self._client

    def process(self, content: bytes, mime_type: str) -> OCRResult:
        """Analyze a document image with Azure DI Layout model."""
        client = self._get_client()

        content_type = (
            mime_type
            if mime_type in {"image/jpeg", "image/png", "image/webp", "application/pdf"}
            else "application/octet-stream"
        )

        try:
            poller = client.begin_analyze_document(
                "prebuilt-layout",
                body=content,
                content_type=content_type,
            )
            result = poller.result()
        except Exception:
            logger.exception("Azure Document Intelligence processing request failed")
            raise

        text = result.content or ""

        confidences = []
        if result.pages:
            for page in result.pages:
                if page.words:
                    for word in page.words:
                        if word.confidence is not None:
                            confidences.append(word.confidence)

        confidence = sum(confidences) / len(confidences) if confidences else None

        return OCRResult(
            text=text,
            confidence=confidence,
        )
