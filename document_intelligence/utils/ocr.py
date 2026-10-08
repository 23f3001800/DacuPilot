import base64
import logging
import json
import mimetypes
from pathlib import Path
from typing import Dict, Any
from datapilot.config import Config
from datapilot.llm_provider import create_completion_with_fallback, create_openai_clients
from ..schemas.documents import (
    DOCUMENT_DATA_FIELDS,
    AadhaarFields,
    BenefitIllustrationFields,
    DrivingLicenceFields,
    FatcaAnnexureFields,
    MoralHazardFields,
    MultiplePoliciesFields,
    NachMandateFields,
    PanFields,
    PassportFields,
    SuitabilityProfilerFields,
)
from .google_document_ai import GoogleDocumentAIProcessor

logger = logging.getLogger(__name__)

DOCUMENT_SCHEMAS = {
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
}

IDENTITY_DOCUMENTS = {
    "AADHAAR_CARD",
    "PAN_CARD",
    "DRIVING_LICENCE",
    "PASSPORT",
}


class MultimodalOCRProcessor:
    """Classifies and extracts fields from one document page per request."""

    def __init__(self):
        Config.validate()
        self.clients = create_openai_clients()
        # Azure DI primary, Google DI secondary, vision LLM final fallback
        self._azure_ocr = None
        self._google_ocr = None
        try:
            from .azure_document_ai import AzureDocumentAIProcessor
            self._azure_ocr = AzureDocumentAIProcessor()
        except Exception:
            logger.info("Azure Document Intelligence not available")
        try:
            self._google_ocr = GoogleDocumentAIProcessor()
        except Exception:
            logger.info("Google Document AI not available")
        self.identity_processor = GoogleIdentityProcessor(self.clients)
        self.form_processor = GoogleFormProcessor(self.clients)

    def _ocr_with_fallback(self, image_bytes: bytes, mime_type: str):
        """Try Azure Document Intelligence (Primary) → Google Cloud Document AI (Secondary) → Vision LLM (Tertiary Fallback)."""
        from .google_document_ai import OCRResult

        # 1. Azure Document Intelligence (Primary OCR)
        if self._azure_ocr is not None:
            try:
                logger.info("Executing Primary OCR: Azure Document Intelligence")
                return self._azure_ocr.process(image_bytes, mime_type)
            except Exception:
                logger.warning("Primary Azure Document Intelligence failed; falling back to Secondary Google Document AI")

        # 2. Google Cloud Document AI (Secondary OCR)
        if self._google_ocr is not None:
            try:
                logger.info("Executing Secondary OCR: Google Cloud Document AI")
                return self._google_ocr.process(image_bytes, mime_type)
            except Exception:
                logger.warning("Secondary Google Document AI failed; falling back to Tertiary Vision LLM")

        # 3. Lightweight vision LLM fallback (Tertiary OCR)
        logger.info("Executing Tertiary OCR: Vision LLM fallback")
        encoded = base64.b64encode(image_bytes).decode("ascii")
        response = create_completion_with_fallback(
            self.clients,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Extract ALL visible text from this document image. "
                                "Preserve the layout structure. Return only the "
                                "extracted text, nothing else."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{encoded}",
                            },
                        },
                    ],
                }
            ],
        )
        text = response.choices[0].message.content or ""
        return OCRResult(text=text, confidence=None)

    @staticmethod
    def encode_image_to_base64(image_path: str) -> str:
        return base64.b64encode(Path(image_path).read_bytes()).decode("ascii")

    def _chat_with_text(
        self,
        recognized_text: str,
        prompt: str,
    ) -> dict[str, Any]:
        response = create_completion_with_fallback(
            self.clients,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "text", "text": f"OCR text:\n{recognized_text}"},
                    ],
                }
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Gemini returned an empty document response.")
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("Gemini response must be a JSON object.")
        return result

    def _classify_text(self, recognized_text: str) -> Dict[str, Any]:
        prompt = f"""
Classify this single identity or insurance document page from its OCR text.
Use the detected field labels and document anchors. Valid document_type values:
{", ".join(DOCUMENT_SCHEMAS)}.
Return JSON with document_type, classification_confidence from 0 to 1,
text_medium (PRINTED, HANDWRITTEN, or MIXED), document_reference (stable
visible ID or null), and is_continuation (true only when it continues the
previous page of the same document). Do not extract personal fields at this step.
Use UNKNOWN and confidence 0 for unsupported pages.
"""
        try:
            return self._chat_with_text(recognized_text, prompt)
        except Exception:
            logger.exception("OCR-text document page classification failed")
            raise

    def classify_page(
        self,
        image_bytes: bytes,
        mime_type: str,
    ) -> Dict[str, Any]:
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError(f"Unsupported image MIME type: {mime_type}")
        ocr_result = self._ocr_with_fallback(image_bytes, mime_type)
        classification = self._classify_text(ocr_result.text)
        classification["ocr_confidence"] = ocr_result.confidence
        return classification

    def extract_page(
        self,
        recognized_text: str,
        document_type: str,
        extractor: "GoogleDocumentProcessor",
    ) -> dict[str, Any]:
        schema = DOCUMENT_SCHEMAS[document_type]
        fields = list(schema.model_fields)
        handwritten_focus = (
            "Pay special attention to handwritten digits and similar characters. "
            "Do not infer unclear account numbers, IFSC codes, TIN/PAN, dates, "
            "places, or checkbox choices."
            if document_type not in IDENTITY_DOCUMENTS
            else "Distinguish printed and handwritten text, and do not infer "
            "unclear identity numbers or dates."
        )
        prompt = f"""
Extract fields from this page classified as {document_type}.
Required fields: {json.dumps(fields)}.
{handwritten_focus}
Return a JSON object whose keys are exactly those field names. Each value must
be an object with: value (string or null), is_handwritten (boolean), and
ai_confidence (number from 0 to 1). Use null and confidence 0 when unreadable.
Checkbox fields must identify a visibly selected option, otherwise return null.
"""
        try:
            return extractor.extract(recognized_text, prompt)
        except Exception:
            logger.exception("Document field extraction failed for %s", document_type)
            raise

    def classify_and_extract_page(
        self,
        image_bytes: bytes,
        mime_type: str,
        progress_callback: Any = None,
    ) -> Dict[str, Any]:
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError(f"Unsupported image MIME type: {mime_type}")
        if progress_callback:
            progress_callback({"step": "ocr", "status": "active", "message": "Recognizing page text with OCR"})
        ocr_result = self._ocr_with_fallback(image_bytes, mime_type)
        if progress_callback:
            conf_str = f" ({round(ocr_result.confidence * 100)}% confidence)" if ocr_result.confidence is not None else ""
            progress_callback({
                "step": "ocr",
                "status": "completed",
                "message": f"OCR text recognized{conf_str}",
                "ocr_confidence": ocr_result.confidence,
            })

        if progress_callback:
            progress_callback({"step": "classification", "status": "active", "message": "Classifying document type from layout anchors"})
        classification = self._classify_text(ocr_result.text)
        classification["ocr_confidence"] = ocr_result.confidence
        document_type = str(classification.get("document_type", "UNKNOWN")).upper()
        cls_conf = classification.get("classification_confidence", 0.0)
        try:
            cls_conf_float = float(cls_conf)
        except (TypeError, ValueError):
            cls_conf_float = 0.0
        if progress_callback:
            progress_callback({
                "step": "classification",
                "status": "completed",
                "message": f"Classified as {document_type} ({round(cls_conf_float * 100)}% confidence)",
                "document_type": document_type,
                "classification_confidence": cls_conf_float,
            })

        if document_type not in DOCUMENT_SCHEMAS:
            return classification
        extractor = (
            self.identity_processor
            if document_type in IDENTITY_DOCUMENTS
            else self.form_processor
        )
        if progress_callback:
            progress_callback({
                "step": "extraction",
                "status": "active",
                "message": f"Extracting schema fields using {extractor.processor_name}",
                "document_type": document_type,
            })
        classification["fields"] = self.extract_page(
            ocr_result.text,
            document_type,
            extractor,
        )
        if progress_callback:
            fields_count = len(classification["fields"]) if isinstance(classification["fields"], dict) else 0
            progress_callback({
                "step": "extraction",
                "status": "completed",
                "message": f"Extracted {fields_count} field(s) for {document_type}",
                "document_type": document_type,
            })
        return classification

    def execute_raw_ocr_analysis(self, image_path: str) -> Dict[str, Any]:
        """Provides spatial text extraction heuristics before parsing structured fields."""
        mime_type = mimetypes.guess_type(image_path)[0]
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError(f"Unsupported image type for OCR: {image_path}")
        ocr_result = self._ocr_with_fallback(
            Path(image_path).read_bytes(),
            mime_type,
        )
        return {
            "raw_text": ocr_result.text,
            "ocr_confidence": ocr_result.confidence,
            "status": "SUCCESS",
        }


class GoogleDocumentProcessor:
    processor_name = "GOOGLE_DOCUMENT_PROCESSOR"

    def __init__(self, clients):
        self.clients = clients

    def extract(
        self,
        recognized_text: str,
        prompt: str,
    ) -> dict[str, Any]:
        response = create_completion_with_fallback(
            self.clients,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "text", "text": f"OCR text:\n{recognized_text}"},
                    ],
                }
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Gemini returned an empty extraction response.")
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError("Gemini extraction must be a JSON object.")
        return result


class GoogleIdentityProcessor(GoogleDocumentProcessor):
    processor_name = "GOOGLE_ID_PROCESSOR"


class GoogleFormProcessor(GoogleDocumentProcessor):
    processor_name = "GOOGLE_FORM_PROCESSOR"
