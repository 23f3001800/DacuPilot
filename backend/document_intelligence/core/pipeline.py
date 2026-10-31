import json
import logging
import math
import mimetypes
import time
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


def _classify_page(
    page: DocumentPage,
    processor: PageProcessor,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    page_index: int = 1,
    total_pages: int = 1,
) -> dict[str, Any]:
    step_events_emitted = set()

    def page_step_callback(event: dict[str, Any]) -> None:
        if progress_callback is not None:
            stage = event.get("step") or event.get("stage", "extraction")
            step_events_emitted.add(stage)
            progress_callback({
                "stage": stage,
                "status": event.get("status", "active"),
                "message": f"[{page.source_file} p{page.page_number}] {event.get('message', '')}",
                "source_file": page.source_file,
                "page_number": page.page_number,
                "current_page": page_index,
                "total_pages": total_pages,
                **{k: v for k, v in event.items() if k not in {"step", "stage", "status", "message"}},
            })

    import inspect
    sig = inspect.signature(processor.classify_and_extract_page)
    if "progress_callback" in sig.parameters or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    ):
        response = processor.classify_and_extract_page(
            page.content, page.mime_type, progress_callback=page_step_callback
        )
    else:
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

    if "ocr" not in step_events_emitted and progress_callback is not None:
        conf_str = f" ({round(ocr_confidence * 100)}% confidence)" if ocr_confidence is not None else ""
        progress_callback({
            "stage": "ocr",
            "status": "completed",
            "message": f"[{page.source_file} p{page.page_number}] OCR text recognized{conf_str}",
            "ocr_confidence": ocr_confidence,
            "source_file": page.source_file,
            "page_number": page.page_number,
            "current_page": page_index,
            "total_pages": total_pages,
        })

    ocr_stage = {
        "stage": "DOCUMENT_AI_OCR",
        "status": "COMPLETED",
        "confidence": ocr_confidence,
    }
    document_type = str(response.get("document_type", "UNKNOWN")).upper()
    classification_confidence = float(
        response.get("classification_confidence", 0.0)
    )
    if not 0 <= classification_confidence <= 1:
        classification_confidence = 0.0

    if "classification" not in step_events_emitted and progress_callback is not None:
        progress_callback({
            "stage": "classification",
            "status": "completed" if document_type in DOCUMENT_SCHEMAS else "failed",
            "message": f"[{page.source_file} p{page.page_number}] Classified as {document_type} ({round(classification_confidence * 100)}% confidence)",
            "document_type": document_type,
            "classification_confidence": classification_confidence,
            "source_file": page.source_file,
            "page_number": page.page_number,
            "current_page": page_index,
            "total_pages": total_pages,
        })

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

    if progress_callback is not None:
        progress_callback({
            "stage": "validation",
            "status": "active",
            "message": f"[{page.source_file} p{page.page_number}] Validating fields and format constraints for {document_type}",
            "document_type": document_type,
            "source_file": page.source_file,
            "page_number": page.page_number,
            "current_page": page_index,
            "total_pages": total_pages,
        })

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

    failures = extraction.system_evaluation_matrix.get("validation_failures", [])
    val_status = "PASSED" if not failures else "REVIEW_REQUIRED"
    if progress_callback is not None:
        progress_callback({
            "stage": "validation",
            "status": "completed",
            "message": f"[{page.source_file} p{page.page_number}] Validation {val_status} ({len(failures)} failure(s))",
            "document_type": document_type,
            "validation_failures": failures,
            "source_file": page.source_file,
            "page_number": page.page_number,
            "current_page": page_index,
            "total_pages": total_pages,
        })

    final_route = extraction.system_evaluation_matrix.get("final_routing_decision", "HUMAN_REVIEWS_REQUIRED")
    flagged = extraction.system_evaluation_matrix.get("flagged_fields", [])
    if progress_callback is not None:
        progress_callback({
            "stage": "confidence_shield",
            "status": "completed",
            "message": f"[{page.source_file} p{page.page_number}] Confidence shield: {final_route} ({len(flagged)} flagged)",
            "document_type": document_type,
            "routing_decision": final_route,
            "flagged_fields_count": len(flagged),
            "source_file": page.source_file,
            "page_number": page.page_number,
            "current_page": page_index,
            "total_pages": total_pages,
        })

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
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Segment, classify, extract, validate, flag, and save uploaded documents."""
    if not files:
        raise ValueError("Upload at least one PDF or image.")
    if processor_factory is None:
        from ..utils.ocr import MultimodalOCRProcessor

        processor_factory = MultimodalOCRProcessor

    pipeline_start = time.perf_counter()
    stage_latencies: dict[str, float] = {}
    seg_start = time.perf_counter()

    if progress_callback is not None:
        progress_callback(
            {
                "stage": "segmentation",
                "status": "active",
                "message": f"Splitting {len(files)} file(s) into pages",
                "total_files": len(files),
            }
        )
    pages = []
    for file_index, (filename, content) in enumerate(files, start=1):
        file_pages = segment_upload(filename, content)
        pages.extend(file_pages)
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "segmentation",
                    "status": "active",
                    "message": f"Prepared {filename} ({len(file_pages)} page(s))",
                    "completed_files": file_index,
                    "total_files": len(files),
                }
            )
    seg_ms = round((time.perf_counter() - seg_start) * 1000, 2)
    stage_latencies["segmentation"] = seg_ms
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "segmentation",
                "status": "completed",
                "message": f"Prepared {len(pages)} page(s) across {len(files)} file(s)",
                "page_count": len(pages),
                "total_files": len(files),
                "latency_ms": seg_ms,
            }
        )
    processor = processor_factory()
    page_results = []
    pages_start = time.perf_counter()
    for page_index, page in enumerate(pages, start=1):
        if progress_callback is not None:
            progress_callback(
                {
                    "stage": "page_start",
                    "status": "active",
                    "message": (
                        f"Processing {page.source_file}, page {page.page_number} "
                        f"({page_index} of {len(pages)})"
                    ),
                    "current_page": page_index,
                    "total_pages": len(pages),
                    "source_file": page.source_file,
                    "page_number": page.page_number,
                }
            )
        page_start = time.perf_counter()
        try:
            page_result = _classify_page(
                page,
                processor,
                progress_callback=progress_callback,
                page_index=page_index,
                total_pages=len(pages),
            )
            page_ms = round((time.perf_counter() - page_start) * 1000, 2)
            page_result["latency_ms"] = page_ms
            page_results.append(page_result)
            if progress_callback is not None:
                progress_callback(
                    {
                        "stage": "page_complete",
                        "status": "completed",
                        "message": (
                            f"{page.source_file}, page {page.page_number}: "
                            f"{page_result['document_type']}"
                        ),
                        "current_page": page_index,
                        "total_pages": len(pages),
                        "source_file": page.source_file,
                        "page_number": page.page_number,
                        "document_type": page_result["document_type"],
                        "latency_ms": page_ms,
                    }
                )
        except Exception as error:
            page_ms = round((time.perf_counter() - page_start) * 1000, 2)
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
                    "latency_ms": page_ms,
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
            if progress_callback is not None:
                progress_callback(
                    {
                        "stage": "page_error",
                        "status": "failed",
                        "message": (
                            f"{page.source_file}, page {page.page_number} "
                            "needs review"
                        ),
                        "current_page": page_index,
                        "total_pages": len(pages),
                        "source_file": page.source_file,
                        "page_number": page.page_number,
                        "error": str(error),
                        "latency_ms": page_ms,
                    }
                )

    stage_latencies["page_processing"] = round(
        (time.perf_counter() - pages_start) * 1000, 2
    )
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "extraction",
                "status": "completed",
                "message": f"Processed {len(pages)} page(s)",
                "current_page": len(pages),
                "total_pages": len(pages),
                "latency_ms": stage_latencies["page_processing"],
            }
        )

    if progress_callback is not None:
        progress_callback(
            {
                "stage": "grouping",
                "status": "active",
                "message": "Evaluating continuation references and grouping related pages",
            }
        )
    group_start = time.perf_counter()
    documents = _group_pages(page_results)
    group_ms = round((time.perf_counter() - group_start) * 1000, 2)
    stage_latencies["grouping"] = group_ms
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "grouping",
                "status": "completed",
                "message": f"Grouped {len(pages)} page(s) into {len(documents)} document(s)",
                "document_count": len(documents),
                "latency_ms": group_ms,
            }
        )

    if progress_callback is not None:
        progress_callback(
            {
                "stage": "review",
                "status": "active",
                "message": "Compiling review ledger and checking review flags",
            }
        )
    review_start = time.perf_counter()
    review_report = _review_report(documents)
    review_ms = round((time.perf_counter() - review_start) * 1000, 2)
    stage_latencies["review"] = review_ms
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "review",
                "status": "completed",
                "message": (
                    f"{len(documents)} document(s) · "
                    f"{len(review_report['flagged_fields'])} item(s) flagged"
                ),
                "flagged_count": len(review_report["flagged_fields"]),
                "human_review_required": review_report["human_review_required"],
                "latency_ms": review_ms,
            }
        )
    job_id = uuid.uuid4().hex
    root = (
        Path(output_root)
        if output_root is not None
        else Path(__file__).resolve().parents[1] / "output"
    )
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "export",
                "status": "active",
                "message": "Creating JSON, review report, and Excel downloads",
            }
        )
    export_start = time.perf_counter()
    outputs = _save_outputs(job_id, documents, review_report, root)
    export_ms = round((time.perf_counter() - export_start) * 1000, 2)
    stage_latencies["export"] = export_ms
    if progress_callback is not None:
        progress_callback(
            {
                "stage": "export",
                "status": "completed",
                "message": "Download files are ready",
                "latency_ms": export_ms,
            }
        )

    total_latency_ms = round((time.perf_counter() - pipeline_start) * 1000, 2)
    logger.info("Pipeline completed in %.2fms", total_latency_ms)
    return {
        "job_id": job_id,
        "document_count": len(documents),
        "page_count": len(pages),
        "threshold": Config.FIELD_CONFIDENCE_THRESHOLD,
        "review_report": review_report,
        "documents": documents,
        "outputs": outputs,
        "total_latency_ms": total_latency_ms,
        "stage_latencies": stage_latencies,
    }
