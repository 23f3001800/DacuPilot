import json
import html
import asyncio
import logging
import time
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import agent
from .operations import ColumnOperationRequest, apply_operation, preview_operation

logger = logging.getLogger("datapilot.api")
router = APIRouter(tags=["data agent"])
MAX_EXCEL_BYTES = 20 * 1024 * 1024
UPLOAD_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "uploads"
CHART_DIRECTORY = UPLOAD_DIRECTORY / "charts"
CHART_INDEX = CHART_DIRECTORY / "index.json"
_chart_artifacts: dict[str, list[dict[str, Any]]] = {}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)


class ChartRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    column: str | None = None


class CleaningRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    operation: str = Field(pattern="^(remove_duplicates|drop_missing_rows)$")


class ApplyCleaningRequest(CleaningRequest):
    operation_id: str = Field(min_length=1)


_pending_cleaning: dict[str, tuple[str, str, Any]] = {}


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


def _json_safe(value: Any) -> Any:
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and value != value:
        return None
    return value


def _chart_svg(title: str, values: list[float]) -> str:
    width, height, pad = 900, 360, 42
    low, high = min(values), max(values)
    span = high - low or 1
    points = []
    for index, value in enumerate(values):
        x = pad + (index / max(1, len(values) - 1)) * (width - (pad * 2))
        y = height - pad - ((value - low) / span) * (height - (pad * 2))
        points.append(f"{x:.1f},{y:.1f}")
    safe_title = html.escape(title)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">'
            f'<rect width="100%" height="100%" fill="#f8faff"/><text x="{pad}" y="28" fill="#17366f" font-family="Arial" font-size="18">{safe_title}</text>'
            f'<polyline points="{" ".join(points)}" fill="none" stroke="#2c67ee" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#cdd9ed"/></svg>')


def _load_chart_index() -> dict[str, list[dict[str, Any]]]:
    if not CHART_INDEX.is_file():
        return {}
    try:
        return json.loads(CHART_INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_chart_index(index: dict[str, list[dict[str, Any]]]) -> None:
    CHART_DIRECTORY.mkdir(parents=True, exist_ok=True)
    CHART_INDEX.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")


def _column_intent(message: str) -> tuple[str, str] | None:
    match = re.search(r"(?:add|create)\s+(?:a\s+)?(?:new\s+)?column\s+['\"]?([^'\"=\n]+?)['\"]?\s+(?:with|using|formula|=)\s*(.+)$", message, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip().rstrip(".")


@router.get("/api/data/preview")
async def data_preview(
    thread_id: str = Query("default", min_length=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    context = agent.get_dataset_context(thread_id)
    if context is None:
        return {"loaded": False, "columns": [], "rows": [], "total_rows": 0, "offset": offset, "limit": limit}
    frame = context.data_frame.iloc[offset:offset + limit]
    rows = [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]
    return {
        "loaded": True,
        "columns": [str(column) for column in context.data_frame.columns],
        "rows": rows,
        "total_rows": len(context.data_frame),
        "offset": offset,
        "limit": limit,
    }


@router.get("/api/data/dashboard")
async def data_dashboard(thread_id: str = Query("default", min_length=1)):
    context = agent.get_dataset_context(thread_id)
    if context is None:
        return {"loaded": False, "kpis": [], "charts": []}
    frame = context.data_frame
    numeric = frame.select_dtypes(include="number")
    kpis = [
        {"label": "Rows", "value": len(frame)},
        {"label": "Columns", "value": len(frame.columns)},
        {"label": "Numeric fields", "value": len(numeric.columns)},
        {"label": "Missing values", "value": int(frame.isna().sum().sum())},
    ]
    charts = []
    for column in list(numeric.columns)[:3]:
        series = numeric[column].dropna().head(20)
        charts.append({
            "type": "line",
            "title": f"{column} trend",
            "labels": [str(index + 1) for index in range(len(series))],
            "series": [{"name": str(column), "values": [_json_safe(value) for value in series.tolist()]}],
        })
    return {"loaded": True, "kpis": kpis, "charts": charts}


@router.post("/api/data/charts/generate")
async def generate_chart(payload: ChartRequest):
    context = agent.get_dataset_context(payload.thread_id)
    if context is None:
        raise HTTPException(status_code=404, detail="No workbook is loaded for this session.")
    numeric = context.data_frame.select_dtypes(include="number")
    column = payload.column if payload.column in numeric.columns else (str(numeric.columns[0]) if len(numeric.columns) else None)
    if column is None:
        raise HTTPException(status_code=400, detail="The workbook has no numeric column to chart.")
    values = [_json_safe(value) for value in numeric[column].dropna().head(100).tolist()]
    values = [float(value) for value in values if value is not None]
    if not values:
        raise HTTPException(status_code=400, detail="The selected column has no numeric values.")
    artifact_id = uuid4().hex
    CHART_DIRECTORY.mkdir(parents=True, exist_ok=True)
    title = f"{column} trend"
    (CHART_DIRECTORY / f"{artifact_id}.svg").write_text(_chart_svg(title, values), encoding="utf-8")
    artifact = {"artifact_id": artifact_id, "title": title, "column": column, "labels": [str(index + 1) for index in range(len(values))], "values": values, "url": f"/api/data/charts/{artifact_id}.svg"}
    _chart_artifacts.setdefault(payload.thread_id, []).append(artifact)
    _chart_artifacts[payload.thread_id] = _chart_artifacts[payload.thread_id][-20:]
    _save_chart_index(_chart_artifacts)
    return artifact


@router.get("/api/data/charts")
async def list_charts(thread_id: str = Query("default", min_length=1)):
    context = agent.get_dataset_context(thread_id)
    if context is None:
        return {"charts": []}
    if not _chart_artifacts:
        _chart_artifacts.update(_load_chart_index())
    return {"charts": _chart_artifacts.get(thread_id, [])}


@router.get("/api/data/charts/{filename}")
async def get_chart(filename: str):
    safe_name = Path(filename).name
    chart_path = CHART_DIRECTORY / safe_name
    if chart_path.suffix != ".svg" or not chart_path.is_file():
        raise HTTPException(status_code=404, detail="Chart artifact not found.")
    return FileResponse(chart_path, media_type="image/svg+xml", filename=safe_name)


async def workflow_event_generator(thread_id: str):
    context = agent.get_dataset_context(thread_id)
    if context is None:
        yield _sse({"event": "error", "message": "Upload a workbook in Data Studio before running this workflow."})
        yield _sse("[DONE]")
        return
    yield _sse({"event": "stage", "stage": "receive", "state": "done", "message": "Workbook received."})
    await asyncio.sleep(0.05)
    yield _sse({"event": "stage", "stage": "profile", "state": "active", "message": "Profiling workbook columns."})
    schema = context.schema
    await asyncio.sleep(0.05)
    yield _sse({"event": "stage", "stage": "profile", "state": "done", "message": "Workbook profile ready."})
    yield _sse({"event": "stage", "stage": "analysis", "state": "active", "message": "Generating workbook metrics."})
    numeric = context.data_frame.select_dtypes(include="number")
    charts = [{"type": "line", "title": f"{column} trend", "labels": [str(index + 1) for index in range(len(numeric[column].dropna().head(20)))], "series": [{"name": str(column), "values": [_json_safe(value) for value in numeric[column].dropna().head(20).tolist()]}]} for column in list(numeric.columns)[:3]]
    await asyncio.sleep(0.05)
    yield _sse({"event": "stage", "stage": "analysis", "state": "done", "message": "Metrics generated."})
    yield _sse({"event": "stage", "stage": "response", "state": "active", "message": "Preparing workflow output."})
    result = {"filename": schema.get("filename"), "rows": schema.get("total_rows", 0), "fields": len(schema.get("columns", [])), "charts": len(charts), "missing": int(context.data_frame.isna().sum().sum())}
    yield _sse({"event": "result", "result": result})
    yield _sse({"event": "stage", "stage": "response", "state": "done", "message": "Workflow completed."})
    yield _sse("[DONE]")


@router.post("/api/workflows/run")
async def run_workflow(thread_id: str = Query("default", min_length=1)):
    return StreamingResponse(workflow_event_generator(thread_id), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/data/column/preview")
async def preview_column_operation(payload: ColumnOperationRequest):
    context = agent.get_dataset_context(payload.thread_id)
    if context is None:
        raise HTTPException(status_code=404, detail="No workbook is loaded for this session.")
    try:
        return await run_in_threadpool(
            preview_operation,
            payload.thread_id,
            context.data_frame,
            payload.column_name,
            payload.formula,
        )
    except (SyntaxError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/data/cleaning/preview")
async def preview_cleaning(payload: CleaningRequest):
    context = agent.get_dataset_context(payload.thread_id)
    if context is None:
        raise HTTPException(status_code=404, detail="No workbook is loaded for this session.")
    frame = context.data_frame.copy()
    if payload.operation == "remove_duplicates":
        updated = frame.drop_duplicates()
        label = "Remove duplicate rows"
    else:
        updated = frame.dropna()
        label = "Remove rows with missing values"
    operation_id = uuid4().hex
    _pending_cleaning[operation_id] = (payload.thread_id, payload.operation, updated)
    return {"operation_id": operation_id, "operation": payload.operation, "label": label,
            "rows_before": len(frame), "rows_after": len(updated), "rows_removed": len(frame) - len(updated),
            "preview": updated.head(5).where(updated.head(5).notna(), None).to_dict(orient="records")}


@router.post("/api/data/cleaning/apply")
async def apply_cleaning(payload: ApplyCleaningRequest):
    pending = _pending_cleaning.pop(payload.operation_id, None)
    if pending is None or pending[0] != payload.thread_id or pending[1] != payload.operation:
        raise HTTPException(status_code=404, detail="Cleaning preview expired. Preview the operation again.")
    _, operation, updated = pending
    version_path = UPLOAD_DIRECTORY / f"{uuid4().hex}.xlsx"
    version_path.parent.mkdir(parents=True, exist_ok=True)
    await run_in_threadpool(updated.to_excel, version_path, index=False)
    schema = await run_in_threadpool(agent.set_dataset, str(version_path), version_path.name, payload.thread_id)
    return {"versioned": True, "operation": operation, "filename": version_path.name,
            "total_rows": schema["total_rows"], "columns": schema["columns"]}


class ApplyColumnOperationRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)


@router.post("/api/data/column/apply")
async def apply_column_operation(payload: ApplyColumnOperationRequest):
    try:
        column_name, updated, formula = await run_in_threadpool(
            apply_operation, payload.operation_id, payload.thread_id
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    version_path = UPLOAD_DIRECTORY / f"{uuid4().hex}.xlsx"
    updated.to_excel(version_path, index=False)
    schema = await run_in_threadpool(
        agent.set_dataset, str(version_path), version_path.name, payload.thread_id
    )
    return {"versioned": True, "filename": version_path.name, "column_name": column_name,
            "formula": formula, "total_rows": schema["total_rows"], "columns": schema["columns"]}


@router.get("/api/data/schema")
async def data_schema(thread_id: str = Query("default", min_length=1)):
    context = agent.get_dataset_context(thread_id)
    if context is None:
        return {
            "loaded": False,
            "filename": None,
            "total_rows": 0,
            "columns": [],
            "data_types": {},
            "summary": {},
        }
    return {"loaded": True, **context.schema}


@router.post("/api/data/upload")
async def upload_excel(
    file: UploadFile = File(...),
    thread_id: str = Form("default", min_length=1),
    sheet_name: str | None = Form(None),
):
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
            agent.set_dataset, str(stored_path), file.filename, thread_id, sheet_name
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


@router.get("/api/data/workbook/download")
async def download_workbook(thread_id: str = Query("default", min_length=1)):
    context = agent.get_dataset_context(thread_id)
    if context is None or not context.file_path or not Path(context.file_path).is_file():
        raise HTTPException(status_code=404, detail="No saved workbook is available for this session.")
    return FileResponse(context.file_path, filename=context.schema.get("filename", Path(context.file_path).name), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.delete("/api/data/workbook")
async def delete_workbook(thread_id: str = Query("default", min_length=1)):
    context = agent.delete_dataset(thread_id)
    if context is None:
        raise HTTPException(status_code=404, detail="No workbook is loaded for this session.")
    if context.file_path:
        Path(context.file_path).unlink(missing_ok=True)
    return {"deleted": True, "thread_id": thread_id}


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
    if not agent.has_dataset(thread_id):
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
            "confidence_score": 0.0,
            "payload": {
                "confidence_score": 0.0,
                "evaluation_rationale": "Guardrail triggered: Dataset upload required before data analysis.",
                "data_coverage_percentage": 0.0,
            },
        })
        yield _sse({"event": "latency", "total_ms": 1.0})
        yield _sse("[DONE]")
        return

    intent = _column_intent(user_message)
    if intent:
        column_name, formula = intent
        context = agent.get_dataset_context(thread_id)
        yield _sse({"event": "status", "text": f"Preparing column {column_name}..."})
        yield _sse({"event": "tool_start", "tool": "safe_column_operation"})
        try:
            preview = await run_in_threadpool(preview_operation, thread_id, context.data_frame, column_name, formula)
            yield _sse({"event": "status", "text": "Applying the validated workbook change..."})
            applied_column, updated, applied_formula = await run_in_threadpool(apply_operation, preview["operation_id"], thread_id)
            version_path = UPLOAD_DIRECTORY / f"{uuid4().hex}.xlsx"
            await run_in_threadpool(updated.to_excel, version_path, index=False)
            schema = await run_in_threadpool(agent.set_dataset, str(version_path), context.schema.get("filename"), thread_id)
            yield _sse({"event": "token", "text": f"Done. I added `{applied_column}` using `{applied_formula}` and saved a new workbook version with {schema['total_rows']} rows. The original workbook was preserved."})
            yield _sse({"event": "evaluation", "confidence_score": 0.98, "payload": {"confidence_score": 0.98, "data_coverage_percentage": 100.0, "evaluation_rationale": "Safe validated column operation applied to the active workbook."}})
        except Exception as error:
            yield _sse({"event": "error", "details": str(error)})
            yield _sse({"event": "token", "text": f"I could not apply that workbook change: {error}"})
        yield _sse({"event": "latency", "total_ms": round((time.perf_counter() - stream_start) * 1000, 2)})
        yield _sse("[DONE]")
        return

    config = {"configurable": {"thread_id": thread_id}}
    initial_input = {
        "messages": [HumanMessage(content=user_message)],
        "thread_id": thread_id,
    }

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
                        conf = metrics.get("confidence_score", 0.0) if isinstance(metrics, dict) else 0.0
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
