import logging
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from datapilot.llm_provider import public_settings
from .core.pipeline import process_uploads

logger = logging.getLogger("datapilot.document_intelligence.api")
router = APIRouter(prefix="/api/documents", tags=["document intelligence"])
OUTPUT_DIRECTORY = Path(__file__).resolve().parent / "output"


class ProcessResponse(BaseModel):
    job_id: str
    document_count: int
    page_count: int
    threshold: float
    review_report: dict
    documents: list[dict]
    outputs: dict[str, str]


@router.get("/settings")
def document_settings():
    return public_settings()


@router.post("/process", response_model=ProcessResponse)
async def process_documents(
    files: list[UploadFile] = File(..., min_length=1),
    external_processing_consent: bool = Form(False),
):
    if not external_processing_consent:
        raise HTTPException(
            status_code=400,
            detail=(
                "Explicit consent is required before document contents are "
                "sent to the configured external OCR/AI services."
            ),
        )
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Upload no more than 20 files.")

    upload_data = []
    for upload in files:
        if not upload.filename:
            raise HTTPException(status_code=400, detail="Every upload needs a filename.")
        upload_data.append((Path(upload.filename).name, await upload.read()))

    logger.info("Accepted consented document job with %s file(s)", len(upload_data))
    try:
        result = await run_in_threadpool(process_uploads, upload_data)
        result["outputs"] = {
            "documents_json": f"/api/documents/{result['job_id']}/documents.json",
            "review_report_json": f"/api/documents/{result['job_id']}/review_report.json",
            "excel": f"/api/documents/{result['job_id']}/documents.xlsx",
        }
        logger.info(
            "Document job %s completed with %s document(s) and %s review flag(s)",
            result["job_id"],
            result["document_count"],
            len(result["review_report"].get("flagged_fields", [])),
        )
        return result
    except ValueError as error:
        logger.warning("Document upload rejected (%s)", type(error).__name__)
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        logger.exception("Document-processing service is unavailable")
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        logger.exception("Document-processing job failed")
        raise HTTPException(
            status_code=500,
            detail="Document processing failed. Check the server log for details.",
        ) from error


@router.get("/{job_id}/{filename}", include_in_schema=False)
async def download_result(job_id: str, filename: str):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(status_code=404, detail="Output not found.")
    allowed_files = {"documents.json", "review_report.json", "documents.xlsx"}
    if filename not in allowed_files:
        raise HTTPException(status_code=404, detail="Output not found.")
    path = OUTPUT_DIRECTORY / job_id / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Output not found.")
    media_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if filename.endswith(".xlsx")
        else "application/json"
    )
    return FileResponse(path, media_type=media_type, filename=filename)
