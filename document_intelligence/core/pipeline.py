import json
import logging
import math
import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from openpyxl import Workbook

from datapilot.config import Config
from ..schemas.documents import (
    DOCUMENT_DATA_FIELDS,
    MasterDocumentIntelligencePayload,
)
from ..schemas.fields import FieldEvaluation
from ..utils.ocr import DOCUMENT_SCHEMAS, IDENTITY_DOCUMENTS

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 50
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
logger = logging.getLogger("datapilot.document_intelligence")


@dataclass(frozen=True)
class DocumentPage:
    source_file: str
    page_number: int
    mime_type: str
    content: bytes


class PageProcessor:
    def classify_and_extract_page(
        self,
        image_bytes: bytes,
        mime_type: str,
    ) -> dict[str, Any]:
        raise NotImplementedError


def segment_upload(
    filename: str,
    content: bytes,
) -> list[DocumentPage]:
    """Convert supported uploads into isolated image pages."""
    suffix = Path(filename).suffix.lower()
    if not content:
        raise ValueError(f"{filename}: file is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"{filename}: exceeds the 20 MB per-file limit.")

    if suffix == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise ValueError(f"{filename}: content is not a valid PDF.")
        try:
            import pymupdf
        except ImportError as error:
            raise RuntimeError("PDF support requires the PyMuPDF package.") from error

        try:
            with pymupdf.open(stream=content, filetype="pdf") as pdf:
                if pdf.page_count == 0:
                    raise ValueError(f"{filename}: PDF has no pages.")
                if pdf.page_count > MAX_PDF_PAGES:
                    raise ValueError(
                        f"{filename}: exceeds the {MAX_PDF_PAGES}-page limit."
                    )
                return [
                    DocumentPage(
                        source_file=Path(filename).name,
                        page_number=page_index + 1,
                        mime_type="image/png",
                        content=pdf.load_page(page_index)
                        .get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
                        .tobytes("png"),
                    )
                    for page_index in range(pdf.page_count)
                ]
        except ValueError:
            raise
        except Exception as error:
            raise ValueError(f"{filename}: could not read PDF pages.") from error

    mime_type = mimetypes.guess_type(filename)[0]
    if suffix in {".jpg", ".jpeg"}:
        mime_type = "image/jpeg"
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise ValueError(
            f"{filename}: only PDF, JPEG, PNG, and WebP files are supported."
        )
    return [
        DocumentPage(
            source_file=Path(filename).name,
            page_number=1,
            mime_type=mime_type,
            content=content,
        )
    ]


def _normalized_field(raw_field: Any, handwritten_default: bool) -> dict[str, Any]:
    if not isinstance(raw_field, dict):
        raw_field = {}
    value = raw_field.get("value")
    confidence = raw_field.get("ai_confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    confidence = min(1.0, max(0.0, confidence))
    return {
        "value": None if value is None else str(value).strip() or None,
        "is_handwritten": bool(
            raw_field.get("is_handwritten")
            if isinstance(raw_field.get("is_handwritten"), bool)
            else handwritten_default
        ),
        "ai_confidence": confidence,
    }


def _classify_page(page: DocumentPage, processor: PageProcessor) -> dict[str, Any]:
    response = processor.classify_and_extract_page(page.content, page.mime_type)
    raw_ocr_confidence = response.get("ocr_confidence")
    try:
        ocr_confidence = float(raw_ocr_confidence)
    except (TypeError, ValueError):
        ocr_confidence = None
    if (
        ocr_confidence is not None
        and (
            not math.isfinite(ocr_confidence)
            or not 0 <= ocr_confidence <= 1
        )
    ):
        ocr_confidence = None
    ocr_stage = {
        "stage": "DOCUMENT_AI_OCR",
        "status": (
            "CONFIDENCE_UNAVAILABLE"
            if ocr_confidence is None
            else "COMPLETED"
        ),
        "confidence": ocr_confidence,
    }
    document_type = str(response.get("document_type", "UNKNOWN")).upper()
    if document_type not in DOCUMENT_SCHEMAS:
        return {
            "source_file": page.source_file,
            "page_number": page.page_number,
            "document_type": "UNKNOWN",
            "processor_route": "UNCLASSIFIED",
            "classification_confidence": 0.0,
            "ocr_confidence": ocr_confidence,
            "document_reference": None,
            "is_continuation": False,
            "error": f"Unsupported or unknown document type: {document_type}",
            "stage_trace": [
                {"stage": "DOCUMENT_SEGMENTATION", "status": "COMPLETED"},
                ocr_stage,
                {"stage": "CLASSIFIER_ROUTER", "status": "REVIEW_REQUIRED"},
                {"stage": "HUMAN_IN_THE_LOOP", "status": "REVIEW_REQUIRED"},
            ],
        }

    classification_confidence = float(
        response.get("classification_confidence", 0.0)
    )
    if not 0 <= classification_confidence <= 1:
        classification_confidence = 0.0
    text_medium = str(response.get("text_medium", "MIXED")).upper()
    if text_medium not in {"PRINTED", "HANDWRITTEN", "MIXED"}:
        text_medium = "MIXED"

    field_schema = DOCUMENT_SCHEMAS[document_type]
    raw_fields = response.get("fields")
    if not isinstance(raw_fields, dict):
        raw_fields = {}
    default_handwritten = text_medium == "HANDWRITTEN"
    fields = {
        name: _normalized_field(raw_fields.get(name), default_handwritten)
        for name in field_schema.model_fields
    }
    data_attr = DOCUMENT_DATA_FIELDS[document_type]
    extraction = MasterDocumentIntelligencePayload(
        document_type=document_type,
        text_medium=text_medium,
        **{data_attr: field_schema(**fields)},
    )
    if classification_confidence < Config.FIELD_CONFIDENCE_THRESHOLD:
        matrix = extraction.system_evaluation_matrix
        matrix["final_routing_decision"] = "HUMAN_REVIEWS_REQUIRED"
        matrix["flagged_fields"].append(
            {
                "field": "document_type",
                "value": document_type,
                "confidence": round(classification_confidence, 3),
                "reason": "CLASSIFICATION_BELOW_CONFIDENCE_THRESHOLD",
            }
        )
    return {
        "source_file": page.source_file,
        "page_number": page.page_number,
        "document_type": document_type,
        "processor_route": (
            "GOOGLE_ID_PROCESSOR"
            if document_type in IDENTITY_DOCUMENTS
            else "GOOGLE_FORM_PROCESSOR"
        ),
        "classification_confidence": classification_confidence,
        "ocr_confidence": response.get("ocr_confidence"),
        "document_reference": response.get("document_reference"),
        "is_continuation": bool(response.get("is_continuation", False)),
        "stage_trace": [
            {"stage": "DOCUMENT_SEGMENTATION", "status": "COMPLETED"},
            ocr_stage,
            {
                "stage": "CLASSIFIER_ROUTER",
                "status": (
                    "PASSED"
                    if classification_confidence >= Config.FIELD_CONFIDENCE_THRESHOLD
                    else "REVIEW_REQUIRED"
                ),
                "confidence": classification_confidence,
            },
            {
                "stage": "DOCUMENT_PROCESSOR",
                "status": "PASSED",
                "route": (
                    "GOOGLE_ID_PROCESSOR"
                    if document_type in IDENTITY_DOCUMENTS
                    else "GOOGLE_FORM_PROCESSOR"
                ),
            },
            {
                "stage": "FIELD_VALIDATION",
                "status": (
                    "PASSED"
                    if not extraction.system_evaluation_matrix["validation_failures"]
                    else "REVIEW_REQUIRED"
                ),
            },
            {
                "stage": "CONFIDENCE_SHIELD",
                "status": extraction.system_evaluation_matrix[
                    "final_routing_decision"
                ],
                "threshold": Config.FIELD_CONFIDENCE_THRESHOLD,
            },
        ],
        "extraction": extraction.model_dump(),
    }


def _fields_for_document(document: dict[str, Any]) -> dict[str, Any]:
    field_block = document["extraction"].get(
        DOCUMENT_DATA_FIELDS[document["document_type"]], {}
    )
    return {
        key: value
        for key, value in field_block.items()
        if isinstance(value, dict) and "ai_confidence" in value
    }


def _group_pages(page_results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    documents: list[dict[str, Any]] = []
    for page_result in page_results:
        previous = documents[-1] if documents else None
        can_continue = (
            page_result.get("is_continuation")
            and previous is not None
            and not previous.get("error")
            and page_result["document_type"] == previous["document_type"]
            and page_result.get("document_reference")
            and page_result["document_reference"]
            == previous.get("document_reference")
        )
        if not can_continue:
            document = dict(page_result)
            document["pages"] = [page_result["page_number"]]
            document["source_files"] = [page_result["source_file"]]
            documents.append(document)
            continue

        previous["pages"].append(page_result["page_number"])
        if page_result["source_file"] not in previous["source_files"]:
            previous["source_files"].append(page_result["source_file"])
        previous_fields = _fields_for_document(previous)
        current_fields = _fields_for_document(page_result)
        for name, field in current_fields.items():
            old_field = previous_fields[name]
            if field["ai_confidence"] > old_field["ai_confidence"]:
                previous_fields[name] = field
        previous["extraction"][
            DOCUMENT_DATA_FIELDS[previous["document_type"]]
        ].update(previous_fields)
        previous["classification_confidence"] = min(
            previous["classification_confidence"],
            page_result["classification_confidence"],
        )
        previous["stage_trace"].extend(page_result["stage_trace"])
    return documents


def _review_report(documents: list[dict[str, Any]]) -> dict[str, Any]:
    flagged = []
    for document_index, document in enumerate(documents, start=1):
        matrix = document.get("extraction", {}).get("system_evaluation_matrix", {})
        for field in matrix.get("flagged_fields", []):
            flagged.append(
                {
                    "document_index": document_index,
                    "source_file": document.get("source_file"),
                    "document_type": document.get("document_type"),
                    **field,
                }
            )
        if document.get("error"):
            flagged.append(
                {
                    "document_index": document_index,
                    "source_file": document.get("source_file"),
                    "document_type": "UNKNOWN",
                    "field": "document",
                    "confidence": 0.0,
                    "reason": document["error"],
                }
            )

    return {
        "threshold": Config.FIELD_CONFIDENCE_THRESHOLD,
        "rationale": Config.FIELD_CONFIDENCE_THRESHOLD_RATIONALE,
        "handwriting_note": (
            "Printed and handwritten fields are both extracted from the page image. "
            "Fields marked handwritten receive the configured conservative "
            "confidence penalty and are individually flagged when below threshold."
        ),
        "flagged_fields": flagged,
        "human_review_required": bool(flagged),
    }


def _save_outputs(
    job_id: str,
    documents: list[dict[str, Any]],
    review_report: dict[str, Any],
    output_root: Path,
) -> dict[str, str]:
    job_dir = output_root / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    documents_path = job_dir / "documents.json"
    report_path = job_dir / "review_report.json"
    workbook_path = job_dir / "documents.xlsx"
    documents_path.write_text(
        json.dumps(documents, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(review_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    workbook = Workbook()
    documents_sheet = workbook.active
    documents_sheet.title = "Documents"
    documents_sheet.append(
        ["Source file", "Pages", "Document type", "Field", "Value", "Confidence", "Review"]
    )
    for document in documents:
        source_files = ", ".join(
            document.get("source_files", [document["source_file"]])
        )
        if document.get("error"):
            documents_sheet.append(
                [
                    source_files,
                    ", ".join(
                        map(
                            str,
                            document.get("pages", [document.get("page_number")]),
                        )
                    ),
                    "UNKNOWN",
                    "document",
                    None,
                    document.get("classification_confidence", 0.0),
                    "Review",
                ]
            )
            continue
        for field_name, field in _fields_for_document(document).items():
            documents_sheet.append(
                [
                    source_files,
                    ", ".join(map(str, document.get("pages", []))),
                    document["document_type"],
                    field_name,
                    field["value"],
                    field["final_field_score"],
                    "Review" if field["requires_human_review"] else "Passed",
                ]
            )

    review_sheet = workbook.create_sheet("Human Review")
    review_sheet.append(
        ["Document", "Type", "Field", "Value", "Confidence", "Reason"]
    )
    for flag in review_report["flagged_fields"]:
        review_sheet.append(
            [
                flag.get("source_file"),
                flag.get("document_type"),
                flag.get("field"),
                flag.get("value"),
                flag.get("confidence"),
                flag.get("reason"),
            ]
        )
    workbook.save(workbook_path)
    return {
        "documents_json": str(documents_path),
        "review_report_json": str(report_path),
        "excel": str(workbook_path),
    }


def process_uploads(
    files: list[tuple[str, bytes]],
    processor_factory: Callable[[], PageProcessor] | None = None,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    """Segment, classify, extract, validate, flag, and save uploaded documents."""
    if not files:
        raise ValueError("Upload at least one PDF or image.")
    if processor_factory is None:
        from ..utils.ocr import MultimodalOCRProcessor

        processor_factory = MultimodalOCRProcessor

    pages = [
        page
        for filename, content in files
        for page in segment_upload(filename, content)
    ]
    processor = processor_factory()
    page_results = []
    for page in pages:
        try:
            page_results.append(_classify_page(page, processor))
        except Exception as error:
            logger.exception(
                "Document page processing failed for page %s", page.page_number
            )
            page_results.append(
                {
                    "source_file": page.source_file,
                    "page_number": page.page_number,
                    "document_type": "UNKNOWN",
                    "processor_route": "UNCLASSIFIED",
                    "classification_confidence": 0.0,
                    "ocr_confidence": None,
                    "document_reference": None,
                    "is_continuation": False,
                    "error": str(error),
                    "stage_trace": [
                        {"stage": "DOCUMENT_SEGMENTATION", "status": "COMPLETED"},
                        {
                            "stage": "DOCUMENT_PROCESSING",
                            "status": "FAILED",
                        },
                        {
                            "stage": "HUMAN_IN_THE_LOOP",
                            "status": "REVIEW_REQUIRED",
                        },
                    ],
                }
            )

    documents = _group_pages(page_results)
    review_report = _review_report(documents)
    job_id = uuid.uuid4().hex
    root = (
        Path(output_root)
        if output_root is not None
        else Path(__file__).resolve().parents[1] / "output"
    )
    outputs = _save_outputs(job_id, documents, review_report, root)
    return {
        "job_id": job_id,
        "document_count": len(documents),
        "page_count": len(pages),
        "threshold": Config.FIELD_CONFIDENCE_THRESHOLD,
        "review_report": review_report,
        "documents": documents,
        "outputs": outputs,
    }
