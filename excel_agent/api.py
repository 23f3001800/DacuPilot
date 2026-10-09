import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import agent

logger = logging.getLogger("datapilot.api")
router = APIRouter(tags=["data agent"])
MAX_EXCEL_BYTES = 20 * 1024 * 1024
UPLOAD_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "uploads"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)


def _sse(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _tool_calls(chunk: Any) -> list[dict[str, Any]]:
    calls = getattr(chunk, "tool_calls", None)
    if calls:
        return calls
    additional = getattr(chunk, "additional_kwargs", {})
    raw_calls = additional.get("tool_calls", []) if isinstance(additional, dict) else []
    return [
        call
        for call in raw_calls
        if isinstance(call, dict)
    ]


@router.get("/api/data/schema")
async def data_schema():
    if agent.schema_context is None:
        return {
            "loaded": False,
            "filename": None,
            "total_rows": 0,
            "columns": [],
            "data_types": {},
            "summary": {},
        }
    return {"loaded": True, **agent.schema_context}


@router.post("/api/data/upload")
async def upload_excel(file: UploadFile = File(...)):
    if not file.filename or Path(file.filename).suffix.lower() not in {".xlsx", ".xlsm"}:
        raise HTTPException(
            status_code=400,
            detail="Upload an Excel workbook with an .xlsx or .xlsm extension.",
        )

    content = await file.read(MAX_EXCEL_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="The workbook is empty.")
    if len(content) > MAX_EXCEL_BYTES:
        raise HTTPException(status_code=413, detail="Workbook exceeds the 20 MB limit.")

    UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    stored_path = UPLOAD_DIRECTORY / f"{uuid4().hex}{Path(file.filename).suffix.lower()}"
    start = time.perf_counter()
    try:
        stored_path.write_bytes(content)
        schema = await run_in_threadpool(
            agent.set_dataset, str(stored_path), file.filename
        )
    except Exception as error:
        stored_path.unlink(missing_ok=True)
        logger.exception("Excel workbook upload failed (%s)", type(error).__name__)
        raise HTTPException(
            status_code=400,
            detail="Could not read the uploaded workbook. Check the file and try again.",
        ) from error

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "Data Agent workbook uploaded in %.2fms (%s rows, %s columns)",
        elapsed_ms,
        schema["total_rows"],
        len(schema["columns"]),
    )
    return {
        "filename": Path(file.filename).name,
        "total_rows": schema["total_rows"],
        "columns": schema["columns"],
        "data_types": schema["data_types"],
        "latency_ms": elapsed_ms,
    }


@router.post("/api/chat/stream")
async def stream_chat_endpoint(payload: ChatRequest):
    logger.info("Starting data-agent stream for thread %s", payload.thread_id)
    return StreamingResponse(
        sse_event_generator(payload.message, payload.thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


from datapilot.guardrails import detect_prompt_injection


async def sse_event_generator(user_message: str, thread_id: str):
    """Stream data-agent tokens, tool starts, metrics, errors, and a final sentinel."""
    stream_start = time.perf_counter()

    is_injected, reason = detect_prompt_injection(user_message)
    if is_injected:
        logger.warning("Prompt injection blocked in data-agent: %s", reason)
        yield _sse({"event": "status", "text": "Safety guardrail active"})
        yield _sse({
            "event": "token",
            "text": (
                "I cannot process this request because it contains instructions "
                "attempting to override system safety policies. Please ask a "
                "question about the workbook dataset."
            ),
        })
        yield _sse({"event": "latency", "total_ms": 1.0})
        yield _sse("[DONE]")
        return

    # 2. Guardrail: User did not provide Excel workbook input
    if agent.df is None or agent.schema_context is None:
        logger.info("Guardrail triggered: No Excel workbook provided for thread %s", thread_id)
        yield _sse({"event": "status", "text": "Workbook Required"})
        yield _sse({
            "event": "token",
            "text": (
                "⚠️ **No Excel workbook has been uploaded yet.**\n\n"
                "Please upload an Excel workbook (`.xlsx` or `.xlsm`) using the **Upload Excel** "
                "button above before asking questions or running calculations."
            ),
        })
        yield _sse({
            "event": "evaluation",
            "confidence_score": 1.0,
            "payload": {
                "confidence_score": 1.0,
                "evaluation_rationale": "Guardrail triggered: Dataset upload required before data analysis.",
                "data_coverage_percentage": 0.0,
            },
        })
        yield _sse({"event": "latency", "total_ms": 1.0})
        yield _sse("[DONE]")
        return

    config = {"configurable": {"thread_id": thread_id}}
    initial_input = {"messages": [HumanMessage(content=user_message)]}

    try:
        yield _sse({"event": "status", "text": "Thinking..."})
        async for event in agent.compiled_graph.astream_events(
            initial_input, config, version="v2"
        ):
            kind = event.get("event")
            data = event.get("data", {})
            chunk = data.get("chunk")
            metadata = event.get("metadata", {})
            graph_node = metadata.get("langgraph_node")

            if kind == "on_chat_model_stream" and chunk is not None:
                if graph_node and graph_node != "analyst_reasoner":
                    continue
                for tool in _tool_calls(chunk):
                    function = tool.get("function", {})
                    tool_name = tool.get("name") or (
                        function.get("name") if isinstance(function, dict) else None
                    )
                    if tool_name:
                        logger.info("Data-agent tool started: %s", tool_name)
                        yield _sse({"event": "tool_start", "tool": tool_name})
                token = _chunk_text(chunk)
                if token:
                    yield _sse({"event": "token", "text": token})
            elif kind == "on_chain_end" and event.get("name") == "run_evaluation":
                output_data = data.get("output", {})
                if isinstance(output_data, dict):
                    result = output_data.get("structured_response")
                    if result is not None:
                        if hasattr(result, "model_dump"):
                            result = result.model_dump()
                        metrics = result.get("evaluation_metrics", {}) if isinstance(result, dict) else {}
                        conf = metrics.get("confidence_score", 0.95) if isinstance(metrics, dict) else 0.95
                        yield _sse({
                            "event": "evaluation",
                            "confidence_score": conf,
                            "payload": result,
                        })
                        yield _sse({"event": "metrics_evaluation", "payload": result})
    except Exception:
        logger.exception("Data-agent stream failed for thread %s", thread_id)
        yield _sse(
            {
                "event": "error",
                "details": "The data assistant failed. Check the server log for details.",
            }
        )
    finally:
        stream_ms = round((time.perf_counter() - stream_start) * 1000, 2)
        logger.info("LATENCY data_agent.stream: %.2fms (thread=%s)", stream_ms, thread_id)
        yield _sse({"event": "latency", "total_ms": stream_ms})
        logger.info("Data-agent stream closed for thread %s", thread_id)
        yield _sse("[DONE]")
