import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from datapilot.latency import track_latency
from datapilot.llm_provider import public_settings
from evals.metrics import pipeline_quality_matrix, routing_matrix, throughput_matrix
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
    latency_ms: float | None = None
    total_latency_ms: float | None = None
    stage_latencies: dict[str, float] | None = None
    evaluation_matrices: dict[str, Any] | None = None


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
        with track_latency("document_intelligence.process", {"file_count": len(upload_data)}) as lat:
            result = await run_in_threadpool(process_uploads, upload_data)
        result["latency_ms"] = lat["latency_ms"]
        result["outputs"] = {
            "documents_json": f"/api/documents/{result['job_id']}/documents.json",
            "review_report_json": f"/api/documents/{result['job_id']}/review_report.json",
            "excel": f"/api/documents/{result['job_id']}/documents.xlsx",
            "evaluation_json": f"/api/documents/{result['job_id']}/evaluation.json",
        }
        result["evaluation_matrices"] = {
            "quality": pipeline_quality_matrix(result["documents"]),
            "throughput": throughput_matrix(
                result["page_count"],
                result.get("total_latency_ms", lat["latency_ms"]),
                stage_latencies=result.get("stage_latencies"),
            ),
            "routing": routing_matrix(result["documents"], result["review_report"]),
        }
        logger.info(
            "Document job %s completed in %.2fms with %s document(s) and %s review flag(s)",
            result["job_id"],
            result["latency_ms"],
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


@router.post("/process/stream")
async def process_documents_stream(
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

    async def event_stream():
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def publish_progress(event: dict) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        stream_start = time.perf_counter()
        worker = asyncio.create_task(
            run_in_threadpool(
                process_uploads,
                upload_data,
                progress_callback=publish_progress,
            )
        )
        worker.add_done_callback(
            lambda _: loop.call_soon_threadsafe(queue.put_nowait, None)
        )
        yield _sse({"type": "progress", "stage": "upload", "status": "completed",
                    "message": f"Received {len(upload_data)} file(s)"})

        while True:
            event = await queue.get()
            if event is None:
                break
            yield _sse({"type": "progress", **event})

        try:
            result = await worker
            stream_ms = round((time.perf_counter() - stream_start) * 1000, 2)
            result["latency_ms"] = stream_ms
            result["outputs"] = {
                "documents_json": f"/api/documents/{result['job_id']}/documents.json",
                "review_report_json": f"/api/documents/{result['job_id']}/review_report.json",
                "excel": f"/api/documents/{result['job_id']}/documents.xlsx",
                "evaluation_json": f"/api/documents/{result['job_id']}/evaluation.json",
            }
            result["evaluation_matrices"] = {
                "quality": pipeline_quality_matrix(result["documents"]),
                "throughput": throughput_matrix(
                    result["page_count"],
                    result.get("total_latency_ms", stream_ms),
                    stage_latencies=result.get("stage_latencies"),
                ),
                "routing": routing_matrix(result["documents"], result["review_report"]),
            }
            logger.info(
                "Streamed document job %s completed in %.2fms with %s document(s)",
                result["job_id"],
                stream_ms,
                result["document_count"],
            )
            yield _sse({"type": "complete", "result": result})
        except ValueError as error:
            logger.warning("Document upload rejected (%s)", type(error).__name__)
            yield _sse({"type": "error", "message": str(error)})
        except RuntimeError as error:
            logger.exception("Document-processing service is unavailable")
            yield _sse({"type": "error", "message": str(error)})
        except Exception:
            logger.exception("Streamed document-processing job failed")
            yield _sse(
                {
                    "type": "error",
                    "message": (
                        "Document processing failed. Check the server log for details."
                    ),
                }
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/{job_id}/evaluation.json")
async def get_job_evaluation(job_id: str):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(status_code=404, detail="Output not found.")
    docs_path = OUTPUT_DIRECTORY / job_id / "documents.json"
    report_path = OUTPUT_DIRECTORY / job_id / "review_report.json"
    if not docs_path.is_file() or not report_path.is_file():
        raise HTTPException(status_code=404, detail="Evaluation not found for this job.")
    try:
        documents = json.loads(docs_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as error:
        raise HTTPException(status_code=500, detail="Failed to load job outputs.") from error
    return {
        "job_id": job_id,
        "quality": pipeline_quality_matrix(documents),
        "routing": routing_matrix(documents, report),
    }


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
