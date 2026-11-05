import json
import html
import logging
import math
import time
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import HumanMessage
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
import pandas as pd
from pydantic import BaseModel, Field, field_validator
from starlette.concurrency import run_in_threadpool

from . import agent
from .operations import ColumnOperationRequest, apply_operation, clear_pending_operations, preview_operation

logger = logging.getLogger("datapilot.api")
router = APIRouter(tags=["data agent"])
MAX_EXCEL_BYTES = 20 * 1024 * 1024
UPLOAD_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "uploads"
CHART_DIRECTORY = UPLOAD_DIRECTORY / "charts"
CHART_INDEX = CHART_DIRECTORY / "index.json"
HISTORY_INDEX = UPLOAD_DIRECTORY / "workbook-history.json"
_chart_artifacts: dict[str, list[dict[str, Any]]] = {}
_chart_index_loaded = False


def _validate_thread_id(value: str) -> str:
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("A valid opaque workspace UUID is required.") from error
    if parsed.version != 4:
        raise ValueError("A version 4 workspace UUID is required.")
    return str(parsed)


def require_thread_id(thread_id: str = Query(..., min_length=36, max_length=36)) -> str:
    try:
        return _validate_thread_id(thread_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


class SessionRequest(BaseModel):
    thread_id: str = Field(min_length=36, max_length=36)

    @field_validator("thread_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _validate_thread_id(value)


class ChatRequest(SessionRequest):
    message: str = Field(min_length=1)
    processing_consent: bool = False


class ChartRequest(SessionRequest):
    column: str | None = None
    category_column: str | None = None


class SheetSelectionRequest(SessionRequest):
    sheet_name: str = Field(min_length=1, max_length=200)


class CleaningRequest(SessionRequest):
    operation: str = Field(pattern="^(remove_duplicates|drop_missing_rows)$")


class ApplyCleaningRequest(CleaningRequest):
    operation_id: str = Field(min_length=1)


_pending_cleaning: dict[str, tuple[str, str, str, Any, float]] = {}
_workbook_versions: dict[str, list[dict[str, str]]] = {}
_history_index_loaded = False
MAX_PENDING_CLEANING = 4


def _prune_pending_cleaning() -> None:
    now = time.monotonic()
    for operation_id, pending in list(_pending_cleaning.items()):
        if pending[4] <= now:
            _pending_cleaning.pop(operation_id, None)


def _clear_pending_work(thread_id: str) -> None:
    clear_pending_operations(thread_id)
    for operation_id, pending in list(_pending_cleaning.items()):
        if pending[0] == thread_id:
            _pending_cleaning.pop(operation_id, None)


def _sse(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(_json_safe(payload), ensure_ascii=False, allow_nan=False)}\n\n"


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
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if pd.api.types.is_scalar(value):
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if hasattr(value, "item"):
            try:
                scalar = value.item()
                if scalar is not value:
                    return _json_safe(scalar)
            except (TypeError, ValueError):
                pass
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, (str, int, bool)):
            return value
        return str(value)
    if isinstance(value, pd.DataFrame):
        return _json_safe(value.to_dict(orient="records"))
    if isinstance(value, pd.Series):
        return _json_safe(value.tolist())
    if hasattr(value, "tolist"):
        try:
            return _json_safe(value.tolist())
        except (TypeError, ValueError):
            pass
    return str(value)


def _chart_svg(title: str, labels: list[str], values: list[float], chart_type: str) -> str:
    width, height, left, right, top, bottom = 900, 400, 70, 24, 56, 82
    plot_width, plot_height = width - left - right, height - top - bottom
    high = max([0, *values]) if values else 0
    low = min([0, *values]) if values else 0
    span = high - low or 1
    safe_title = html.escape(title)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">',
        '<rect width="100%" height="100%" fill="#fff"/>',
        f'<text x="{left}" y="30" fill="#17366f" font-family="Arial" font-size="20" font-weight="700">{safe_title}</text>',
    ]
    for tick in range(5):
        value = high - (span * tick / 4)
        y = top + (plot_height * tick / 4)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="#e8eef7"/>')
        parts.append(f'<text x="{left-10}" y="{y+4:.1f}" text-anchor="end" fill="#697b98" font-family="Arial" font-size="11">{value:,.3g}</text>')
    parts.append(f'<line x1="{left}" y1="{top+plot_height}" x2="{width-right}" y2="{top+plot_height}" stroke="#b8c6dc"/>')
    if chart_type == "bar":
        slot = plot_width / max(1, len(values))
        bar_width = slot * 0.62
        zero_y = top + (high / span) * plot_height
        for index, value in enumerate(values):
            x = left + slot * index + (slot - bar_width) / 2
            value_y = top + ((high - value) / span) * plot_height
            y = min(zero_y, value_y)
            label = html.escape(labels[index][:18])
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{max(1, abs(zero_y-value_y)):.1f}" rx="5" fill="#3478f6"/>')
            parts.append(f'<text x="{x+bar_width/2:.1f}" y="{top+plot_height+22}" text-anchor="middle" fill="#526580" font-family="Arial" font-size="10">{label}</text>')
    else:
        points = []
        for index, value in enumerate(values):
            x = left + (index / max(1, len(values)-1)) * plot_width
            y = top + ((high-value)/span) * plot_height
            points.append(f"{x:.1f},{y:.1f}")
            if len(values) <= 12:
                label = html.escape(labels[index][:12])
                parts.append(f'<text x="{x:.1f}" y="{top+plot_height+22}" text-anchor="middle" fill="#526580" font-family="Arial" font-size="10">{label}</text>')
        parts.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="#3478f6" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')
        for point in points:
            x, y = point.split(",")
            parts.append(f'<circle cx="{x}" cy="{y}" r="4" fill="#3478f6"/>')
    parts.append("</svg>")
    return "".join(parts)


def _load_chart_index() -> dict[str, list[dict[str, Any]]]:
    if not CHART_INDEX.is_file():
        return {}
    try:
        return json.loads(CHART_INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_chart_index(index: dict[str, list[dict[str, Any]]]) -> None:
    _write_json_atomic(CHART_INDEX, index)


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.stem}-{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _clear_charts_for_session(thread_id: str) -> None:
    _ensure_chart_index_loaded()
    for chart in _chart_artifacts.pop(thread_id, []):
        chart_path = CHART_DIRECTORY / Path(chart.get("url", "")).name
        if chart_path.suffix == ".svg" and chart_path.parent.resolve() == CHART_DIRECTORY.resolve():
            chart_path.unlink(missing_ok=True)
    _save_chart_index(_chart_artifacts)


def _ensure_chart_index_loaded() -> None:
    global _chart_index_loaded
    if not _chart_index_loaded:
        _chart_artifacts.update(_load_chart_index())
        _chart_index_loaded = True


def _register_chart(
    thread_id: str,
    frame: Any,
    column: str | None = None,
    semantic_types: dict[str, str] | None = None,
    category_column: str | None = None,
) -> dict[str, Any]:
    numeric = frame.select_dtypes(include="number")
    if column is not None and column not in numeric.columns:
        raise ValueError(f"Column '{column}' is not a numeric field that can be charted.")
    target = column if column in numeric.columns else (str(numeric.columns[0]) if len(numeric.columns) else None)
    if target is None:
        raise ValueError("The workbook has no numeric column to chart.")

    category = None
    date_category = None
    if category_column is not None:
        if category_column not in frame.columns or category_column == target:
            raise ValueError(f"Column '{category_column}' cannot be used as the chart category.")
        if pd.api.types.is_datetime64_any_dtype(frame[category_column]) or (semantic_types or {}).get(str(category_column)) in {"date", "date text"}:
            date_category = category_column
        else:
            category = category_column
    else:
        for candidate in frame.columns:
            if candidate == target:
                continue
            if pd.api.types.is_datetime64_any_dtype(frame[candidate]) or (semantic_types or {}).get(str(candidate)) in {"date", "date text"}:
                date_category = candidate
                break
            if str(frame[candidate].dtype) not in {"object", "category", "bool"}:
                continue
            unique_count = frame[candidate].nunique(dropna=True)
            if 1 < unique_count <= 20:
                category = candidate
                break

    valid_dates = None
    date_periods = None
    if date_category is not None:
        date_values = pd.to_datetime(frame[date_category], errors="coerce", format="mixed")
        valid_dates = date_values.notna() & frame[target].notna()
        if valid_dates.any():
            date_periods = date_values.dt.to_period("M").astype(str)
        else:
            date_category = None

    if date_category is not None:
        grouped = frame.loc[valid_dates].groupby(date_periods.loc[valid_dates], sort=True)[target].sum()
        pairs = [(str(label), float(value)) for label, value in grouped.items() if value is not None and math.isfinite(float(value))]
        labels = [label for label, _ in pairs]
        values = [value for _, value in pairs]
        category = date_category
        chart_type = "line"
        aggregation = "sum"
        title = f"{target} by month · {date_category} · sum"
    elif category is not None:
        grouped = frame.groupby(category, dropna=True, sort=False)[target].sum().sort_values(ascending=False).head(15)
        pairs = [(str(label), float(value)) for label, value in zip(grouped.index.tolist(), grouped.tolist()) if value is not None and math.isfinite(float(value))]
        labels = [label for label, _ in pairs]
        values = [value for _, value in pairs]
        chart_type = "bar"
        aggregation = "sum"
        title = f"{target} by {category} · sum"
    else:
        series = numeric[target].dropna()
        if series.empty:
            raise ValueError(f"Column '{target}' has no numeric values to chart.")
        bin_count = min(10, max(1, math.ceil(math.sqrt(len(series)))))
        distribution = pd.cut(series, bins=bin_count, duplicates="drop").value_counts(sort=False)
        pairs = [(str(interval), int(count)) for interval, count in distribution.items()]
        labels = [label for label, _ in pairs]
        values = [value for _, value in pairs]
        chart_type = "bar"
        aggregation = "frequency"
        title = f"Distribution of {target} · frequency"
        category = None
    if not values:
        raise ValueError(f"Column '{target}' has no numeric values to chart.")

    _ensure_chart_index_loaded()
    artifact_id = uuid4().hex
    CHART_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (CHART_DIRECTORY / f"{artifact_id}.svg").write_text(_chart_svg(title, labels, values, chart_type), encoding="utf-8")
    artifact = {
        "artifact_id": artifact_id,
        "title": title,
        "column": target,
        "category_column": str(category) if category is not None else None,
        "aggregation": aggregation,
        "type": chart_type,
        "labels": labels,
        "values": values,
        "url": f"/api/data/charts/{artifact_id}.svg",
    }
    _chart_artifacts[thread_id] = (_chart_artifacts.get(thread_id, []) + [artifact])[-20:]
    _save_chart_index(_chart_artifacts)
    return artifact


def _ensure_workbook_history_loaded() -> None:
    global _history_index_loaded
    if _history_index_loaded:
        return
    if HISTORY_INDEX.is_file():
        try:
            payload = json.loads(HISTORY_INDEX.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                upload_root = UPLOAD_DIRECTORY.resolve()
                for session_id, entries in payload.items():
                    try:
                        if UUID(session_id).version != 4 or not isinstance(entries, list):
                            continue
                        valid_entries = []
                        for entry in entries:
                            if not isinstance(entry, dict):
                                continue
                            path = Path(entry.get("file_path", "")).resolve()
                            path.relative_to(upload_root)
                            if path.is_file() and isinstance(entry.get("filename"), str):
                                valid_entries.append({**entry, "file_path": str(path)})
                        _workbook_versions[session_id] = valid_entries
                    except (ValueError, TypeError, OSError):
                        continue
        except (OSError, json.JSONDecodeError):
            logger.exception("Could not load saved workbook version history")
    _history_index_loaded = True


def _save_workbook_history() -> None:
    _write_json_atomic(HISTORY_INDEX, _workbook_versions)


def _write_workbook_version(context: Any, frame: Any) -> Path:
    """Write changed data back into its selected sheet while retaining other sheets."""
    UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
    source_path = Path(context.file_path) if context and context.file_path else None
    extension = source_path.suffix.lower() if source_path and source_path.suffix.lower() in {".xlsx", ".xlsm"} else ".xlsx"
    destination = UPLOAD_DIRECTORY / f"{uuid4().hex}{extension}"
    if source_path is None or not source_path.is_file():
        frame.to_excel(destination, index=False)
        return destination

    workbook = load_workbook(source_path, keep_vba=extension == ".xlsm")
    selected_sheet = context.schema.get("selected_sheet") or workbook.active.title
    if selected_sheet not in workbook.sheetnames:
        workbook.close()
        raise ValueError(f"Selected worksheet '{selected_sheet}' is missing from the workbook.")
    sheet = workbook[selected_sheet]
    header_row = max(1, int(context.schema.get("header_row", 1)))
    for merged in list(sheet.merged_cells.ranges):
        if merged.min_row <= header_row <= merged.max_row:
            sheet.unmerge_cells(str(merged))
    data_start = header_row + 1
    if sheet.max_row >= data_start:
        sheet.delete_rows(data_start, sheet.max_row - data_start + 1)

    original_columns = list(context.schema.get("columns", [])) if context else []
    for column_index, column_name in enumerate(frame.columns, start=1):
        sheet.cell(row=header_row, column=column_index, value=str(column_name))
    for column_index in range(len(frame.columns) + 1, len(original_columns) + 1):
        sheet.cell(row=header_row, column=column_index).value = None
    for row_index, values in enumerate(frame.itertuples(index=False, name=None), start=data_start):
        for column_index, value in enumerate(values, start=1):
            if value is not None:
                try:
                    if bool(pd.isna(value)):
                        value = None
                except (TypeError, ValueError):
                    pass
            if hasattr(value, "item"):
                value = value.item()
            if hasattr(value, "to_pydatetime"):
                value = value.to_pydatetime()
            sheet.cell(row=row_index, column=column_index, value=value)

    last_column = get_column_letter(max(1, len(frame.columns)))
    last_row = header_row + len(frame)
    for table in sheet.tables.values():
        table.ref = f"A{header_row}:{last_column}{last_row}"
    if sheet.auto_filter.ref:
        sheet.auto_filter.ref = f"A{header_row}:{last_column}{last_row}"
    workbook.save(destination)
    workbook.close()
    return destination


def _workbook_revision(context: Any) -> str:
    file_path = str(Path(context.file_path).resolve()) if context.file_path else "unsaved"
    return f"{file_path}::{context.schema.get('selected_sheet') or ''}"


def _column_intent(message: str) -> tuple[str, str, str | None] | None:
    match = re.match(
        r"\s*(?P<verb>add|create|insert|modify|update|change|edit|delete|remove)"
        r"\s+(?:(?:a|an|the|new|existing)\s+)*(?:calculated\s+)?column\b(?P<rest>.*)$",
        message,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    remainder = match.group("rest").strip()
    separator = re.search(r"\s+(?:using|with|formula|to|as)\s+|\s*[:=]\s*", remainder, re.IGNORECASE)
    if separator:
        column_name = remainder[:separator.start()].strip().strip("\"'")
        formula = remainder[separator.end():].strip().rstrip(".") or None
    else:
        column_name = remainder.strip().strip("\"'")
        formula = None
    if not column_name:
        return None
    verb = match.group("verb").casefold()
    operation = "add" if verb in {"add", "create", "insert"} else "delete" if verb in {"delete", "remove"} else "update"
    if operation != "delete" and not formula:
        return None
    return operation, column_name, formula


def _is_unparsed_column_change(message: str) -> bool:
    """Catch write requests that cannot enter the explicit preview workflow."""
    normalized = message.casefold()
    if re.search(r"\bdf\s*\[[^\]]+\]\s*=", normalized, re.DOTALL):
        return True
    return bool(
        re.search(
            r"\b(?:add|create|insert|modify|change|update|edit|delete|remove)\b"
            r".{0,80}\b(?:column|columns|field|fields)\b",
            normalized,
            re.DOTALL,
        )
    )


@router.get("/api/data/preview")
async def data_preview(
    thread_id: str = Depends(require_thread_id),
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
async def data_dashboard(thread_id: str = Depends(require_thread_id)):
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
    _ensure_chart_index_loaded()
    # A dashboard contains only generated chart artifacts. Never fabricate a
    # row-number line chart and label it a trend.
    charts = _chart_artifacts.get(thread_id, [])
    return _json_safe({"loaded": True, "kpis": kpis, "charts": charts})


@router.post("/api/data/charts/generate")
async def generate_chart(payload: ChartRequest):
    context = agent.get_dataset_context(payload.thread_id)
    if context is None:
        raise HTTPException(status_code=404, detail="No workbook is loaded for this session.")
    try:
        artifact = await run_in_threadpool(
            _register_chart,
            payload.thread_id,
            context.data_frame,
            payload.column,
            context.schema.get("semantic_types"),
            payload.category_column,
        )
        return _json_safe(artifact)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/data/charts")
async def list_charts(thread_id: str = Depends(require_thread_id)):
    context = agent.get_dataset_context(thread_id)
    if context is None:
        return {"charts": []}
    _ensure_chart_index_loaded()
    return _json_safe({"charts": _chart_artifacts.get(thread_id, [])})


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
    yield _sse({"event": "stage", "stage": "profile", "state": "active", "message": "Profiling workbook columns."})
    schema = context.schema
    frame = context.data_frame
    column_profiles = [
        {"column": str(column), "dtype": str(frame[column].dtype), "missing": int(frame[column].isna().sum()), "unique": int(frame[column].nunique(dropna=True))}
        for column in frame.columns
    ]
    yield _sse({"event": "stage", "stage": "profile", "state": "done", "message": "Workbook profile ready."})
    yield _sse({"event": "stage", "stage": "analysis", "state": "active", "message": "Generating workbook metrics."})
    numeric = frame.select_dtypes(include="number")
    charts = []
    for column in list(numeric.columns)[:3]:
        try:
            charts.append(await run_in_threadpool(_register_chart, thread_id, frame, str(column), schema.get("semantic_types")))
        except ValueError:
            logger.exception("Could not generate a workflow chart for %s", column)
    yield _sse({"event": "stage", "stage": "analysis", "state": "done", "message": "Metrics generated."})
    yield _sse({"event": "stage", "stage": "response", "state": "active", "message": "Preparing workflow output."})
    missing = int(frame.isna().sum().sum())
    result = {
        "filename": schema.get("filename"),
        "rows": schema.get("total_rows", 0),
        "fields": len(schema.get("columns", [])),
        "charts": len(charts),
        "chart_artifacts": charts,
        "missing": missing,
        "column_profiles": column_profiles,
        "summary": f"Profiled {len(frame):,} rows across {len(frame.columns)} fields. Found {missing:,} missing cells and generated {len(charts)} workbook chart(s).",
    }
    yield _sse({"event": "result", "result": result})
    yield _sse({"event": "stage", "stage": "response", "state": "done", "message": "Workflow completed."})
    yield _sse("[DONE]")


@router.post("/api/workflows/run")
async def run_workflow(thread_id: str = Depends(require_thread_id)):
    return StreamingResponse(workflow_event_generator(thread_id), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/api/data/column/preview")
async def preview_column_operation(payload: ColumnOperationRequest):
    try:
        _validate_thread_id(payload.thread_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    context = agent.get_dataset_context(payload.thread_id)
    if context is None:
        raise HTTPException(status_code=404, detail="No workbook is loaded for this session.")
    try:
        preview = await run_in_threadpool(
            preview_operation,
            payload.thread_id,
            context.data_frame,
            payload.column_name,
            payload.formula,
            _workbook_revision(context),
            payload.operation,
        )
        return _json_safe(preview)
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
    _prune_pending_cleaning()
    if len(_pending_cleaning) >= MAX_PENDING_CLEANING:
        raise HTTPException(status_code=429, detail="Too many pending cleaning previews. Apply or discard one first.")
    operation_id = uuid4().hex
    _pending_cleaning[operation_id] = (
        payload.thread_id, payload.operation, _workbook_revision(context), updated, time.monotonic() + 600
    )
    return _json_safe({"operation_id": operation_id, "operation": payload.operation, "label": label,
            "rows_before": len(frame), "rows_after": len(updated), "rows_removed": len(frame) - len(updated),
            "preview": updated.head(5).where(updated.head(5).notna(), None).to_dict(orient="records")})


@router.post("/api/data/cleaning/apply")
async def apply_cleaning(payload: ApplyCleaningRequest):
    _prune_pending_cleaning()
    pending = _pending_cleaning.pop(payload.operation_id, None)
    if pending is None or pending[0] != payload.thread_id or pending[1] != payload.operation:
        raise HTTPException(status_code=404, detail="Cleaning preview expired. Preview the operation again.")
    previous_context = agent.get_dataset_context(payload.thread_id)
    if previous_context is None:
        raise HTTPException(status_code=404, detail="The workbook session ended before this change was applied.")
    _, operation, expected_revision, updated, _expires_at = pending
    if expected_revision != _workbook_revision(previous_context):
        raise HTTPException(status_code=409, detail="The workbook changed after this preview. Preview the cleaning operation again.")
    if previous_context and previous_context.file_path and Path(previous_context.file_path).is_file():
        _ensure_workbook_history_loaded()
        _workbook_versions.setdefault(payload.thread_id, []).append({
            "file_path": previous_context.file_path,
            "filename": previous_context.schema.get("filename", Path(previous_context.file_path).name),
            "sheet_name": previous_context.schema.get("selected_sheet"),
            "operation": operation,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    version_path = await run_in_threadpool(_write_workbook_version, previous_context, updated)
    version_filename = previous_context.schema.get("filename", version_path.name) if previous_context else version_path.name
    schema = await run_in_threadpool(
        agent.set_dataset,
        str(version_path),
        version_filename,
        payload.thread_id,
        previous_context.schema.get("selected_sheet"),
    )
    _save_workbook_history()
    return {"versioned": True, "operation": operation, "filename": version_filename,
            "total_rows": schema["total_rows"], "columns": schema["columns"]}


@router.get("/api/data/history")
async def workbook_history(thread_id: str = Depends(require_thread_id)):
    _ensure_workbook_history_loaded()
    versions = _workbook_versions.get(thread_id, [])
    restorable = [version for version in versions if Path(version["file_path"]).is_file()]
    return {"versions": [{"filename": version["filename"], "operation": version.get("operation", "Workbook change"), "created_at": version.get("created_at"), "restorable": Path(version["file_path"]).is_file()} for version in reversed(versions)],
            "can_undo": bool(restorable)}


@router.post("/api/data/history/undo")
async def undo_workbook_change(thread_id: str = Depends(require_thread_id)):
    _ensure_workbook_history_loaded()
    versions = _workbook_versions.get(thread_id, [])
    if not versions:
        raise HTTPException(status_code=404, detail="No earlier workbook version is available to restore.")
    previous = versions[-1]
    try:
        path = Path(previous["file_path"]).resolve()
        path.relative_to(UPLOAD_DIRECTORY.resolve())
    except (KeyError, ValueError, OSError):
        raise HTTPException(status_code=410, detail="The earlier workbook version is outside managed storage.")
    if not path.is_file():
        raise HTTPException(status_code=410, detail="The earlier workbook version is no longer available on disk.")
    schema = await run_in_threadpool(
        agent.set_dataset, str(path), previous["filename"], thread_id, previous.get("sheet_name")
    )
    versions.pop()
    _save_workbook_history()
    return {"restored": True, "filename": previous["filename"], "total_rows": schema["total_rows"], "columns": schema["columns"]}


class ApplyColumnOperationRequest(SessionRequest):
    operation_id: str = Field(min_length=1)


@router.post("/api/data/column/apply")
async def apply_column_operation(payload: ApplyColumnOperationRequest):
    previous_context = agent.get_dataset_context(payload.thread_id)
    if previous_context is None:
        raise HTTPException(status_code=404, detail="The workbook session ended before this change was applied.")
    try:
        column_name, updated, formula, operation = await run_in_threadpool(
            apply_operation, payload.operation_id, payload.thread_id, _workbook_revision(previous_context)
        )
    except ValueError as error:
        status_code = 409 if "workbook changed" in str(error).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(error)) from error
    version_path = await run_in_threadpool(_write_workbook_version, previous_context, updated)
    version_filename = previous_context.schema.get("filename", version_path.name) if previous_context else version_path.name
    schema = await run_in_threadpool(
        agent.set_dataset,
        str(version_path),
        version_filename,
        payload.thread_id,
        previous_context.schema.get("selected_sheet"),
    )
    if previous_context and previous_context.file_path and Path(previous_context.file_path).is_file():
        _ensure_workbook_history_loaded()
        _workbook_versions.setdefault(payload.thread_id, []).append({
            "file_path": previous_context.file_path,
            "filename": previous_context.schema.get("filename", Path(previous_context.file_path).name),
            "sheet_name": previous_context.schema.get("selected_sheet"),
            "operation": f"{operation.title()} column: {column_name}",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        _save_workbook_history()
    return {"versioned": True, "operation": operation, "filename": version_filename, "column_name": column_name,
            "formula": formula, "total_rows": schema["total_rows"], "columns": schema["columns"]}


@router.get("/api/data/schema")
async def data_schema(thread_id: str = Depends(require_thread_id)):
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
    return _json_safe({"loaded": True, **context.schema})


@router.post("/api/data/sheets/select")
async def select_workbook_sheet(payload: SheetSelectionRequest):
    context = agent.get_dataset_context(payload.thread_id)
    if context is None or not context.file_path:
        raise HTTPException(status_code=404, detail="No saved workbook is available for this session.")
    try:
        schema = await run_in_threadpool(
            agent.set_dataset,
            context.file_path,
            context.schema.get("filename"),
            payload.thread_id,
            payload.sheet_name,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _json_safe({"loaded": True, **schema})


@router.post("/api/data/upload")
async def upload_excel(
    file: UploadFile = File(...),
    thread_id: str = Form(..., min_length=36, max_length=36),
    sheet_name: str | None = Form(None),
):
    try:
        thread_id = _validate_thread_id(thread_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
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
    previous_context = agent.get_dataset_context(thread_id)
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

    if previous_context:
        _clear_pending_work(thread_id)
        agent.reset_agent_conversation(thread_id)
    if previous_context and previous_context.file_path and Path(previous_context.file_path).is_file():
        try:
            previous_path = Path(previous_context.file_path).resolve()
            previous_path.relative_to(UPLOAD_DIRECTORY.resolve())
            _ensure_workbook_history_loaded()
            _workbook_versions.setdefault(thread_id, []).append({
                "file_path": str(previous_path),
                "filename": previous_context.schema.get("filename", previous_path.name),
                "sheet_name": previous_context.schema.get("selected_sheet"),
                "operation": "Replace workbook upload",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            _save_workbook_history()
        except ValueError:
            logger.warning("Ignored a previous workbook outside managed upload storage")
    if previous_context:
        _clear_charts_for_session(thread_id)

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "Data Agent workbook uploaded in %.2fms (%s rows, %s columns)",
        elapsed_ms,
        schema["total_rows"],
        len(schema["columns"]),
    )
    return _json_safe({
        "filename": Path(file.filename).name,
        "total_rows": schema["total_rows"],
        "columns": schema["columns"],
        "data_types": schema["data_types"],
        "latency_ms": elapsed_ms,
    })


@router.get("/api/data/workbook/download")
async def download_workbook(thread_id: str = Depends(require_thread_id)):
    context = agent.get_dataset_context(thread_id)
    if context is None or not context.file_path or not Path(context.file_path).is_file():
        raise HTTPException(status_code=404, detail="No saved workbook is available for this session.")
    media_type = "application/vnd.ms-excel.sheet.macroEnabled.12" if Path(context.file_path).suffix.lower() == ".xlsm" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(context.file_path, filename=context.schema.get("filename", Path(context.file_path).name), media_type=media_type)


@router.delete("/api/data/workbook")
async def delete_workbook(thread_id: str = Depends(require_thread_id)):
    context = agent.delete_dataset(thread_id)
    if context is None:
        raise HTTPException(status_code=404, detail="No workbook is loaded for this session.")
    agent.reset_agent_conversation(thread_id)
    _clear_pending_work(thread_id)
    if context.file_path:
        active_path = Path(context.file_path).resolve()
        try:
            active_path.relative_to(UPLOAD_DIRECTORY.resolve())
            active_path.unlink(missing_ok=True)
        except ValueError:
            logger.warning("Skipped deleting workbook outside upload storage: %s", active_path)
    _ensure_workbook_history_loaded()
    versions = _workbook_versions.pop(thread_id, [])
    for version in versions:
        version_path = Path(version.get("file_path", "")).resolve()
        try:
            version_path.relative_to(UPLOAD_DIRECTORY.resolve())
            version_path.unlink(missing_ok=True)
        except ValueError:
            logger.warning("Skipped deleting workbook version outside upload storage: %s", version_path)
    _save_workbook_history()
    _clear_charts_for_session(thread_id)
    return {"deleted": True, "thread_id": thread_id}


@router.post("/api/chat/stream")
async def stream_chat_endpoint(payload: ChatRequest):
    if agent.has_dataset(payload.thread_id) and not payload.processing_consent:
        raise HTTPException(
            status_code=403,
            detail="Confirm workbook-processing consent before running Data Analysis Agent requests.",
        )
    logger.info("Starting data-agent stream for session %s", agent._fingerprint(payload.thread_id))
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
        yield _sse({"event": "latency", "total_ms": round((time.perf_counter() - stream_start) * 1000, 2)})
        yield _sse("[DONE]")
        return

    # 2. Guardrail: User did not provide Excel workbook input
    if not agent.has_dataset(thread_id):
        logger.info("Guardrail triggered: no workbook for session %s", agent._fingerprint(thread_id))
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
            "confidence_score": None,
            "payload": {
                "confidence_score": None,
                "evaluation_rationale": "Not scored because no workbook was loaded.",
                "data_coverage_percentage": 0.0,
            },
        })
        yield _sse({"event": "latency", "total_ms": round((time.perf_counter() - stream_start) * 1000, 2)})
        yield _sse("[DONE]")
        return

    intent = _column_intent(user_message)
    if intent:
        operation, column_name, formula = intent
        context = agent.get_dataset_context(thread_id)
        yield _sse({"event": "status", "text": f"Preparing column {column_name}..."})
        yield _sse({"event": "tool_start", "tool": "safe_column_operation"})
        try:
            preview = await run_in_threadpool(
                preview_operation,
                thread_id,
                context.data_frame,
                column_name,
                formula,
                _workbook_revision(context),
                operation,
            )
            yield _sse({"event": "change_preview", "preview": preview})
            yield _sse({"event": "status", "text": "Preview ready · waiting for your approval"})
            formula_text = f" using `{formula}`" if formula else ""
            yield _sse({"event": "token", "text": f"I prepared a preview to {operation} column `{column_name}`{formula_text}. Review the before and after values, then apply it to save a new workbook version. The current workbook is unchanged until you approve it."})
            validation = preview.get("validation", {})
            yield _sse({
                "event": "evaluation",
                "confidence_score": None,
                "payload": {
                    "confidence_score": None,
                    "data_coverage_percentage": validation.get("result_coverage_percentage"),
                    "evaluation_rationale": "The formula was evaluated across the workbook rows. Model confidence is not scored for this deterministic preview.",
                },
            })
        except Exception as error:
            yield _sse({"event": "error", "details": str(error)})
            yield _sse({"event": "token", "text": f"I could not prepare that workbook change: {error}"})
        yield _sse({"event": "latency", "total_ms": round((time.perf_counter() - stream_start) * 1000, 2)})
        yield _sse("[DONE]")
        return

    if _is_unparsed_column_change(user_message):
        message = (
            "I couldn’t identify one supported column change, so the workbook is "
            "unchanged. To add a calculated column, use: Add column <name> using "
            "<formula>. The app will show a preview and wait for your approval "
            "before saving. Updating or deleting an existing column is not "
            "available through this preview flow yet. I won’t provide local Python "
            "as a workaround."
        )
        yield _sse({"event": "status", "text": "Column change needs a clear in-app preview request"})
        yield _sse({"event": "token", "text": message})
        yield _sse({"event": "evaluation", "confidence_score": None, "payload": {
            "confidence_score": None,
            "evaluation_rationale": "Not scored because no workbook change was prepared.",
        }})
        yield _sse({"event": "latency", "total_ms": round((time.perf_counter() - stream_start) * 1000, 2)})
        yield _sse("[DONE]")
        return

    config = {"configurable": {"thread_id": thread_id}}
    initial_input = {
        "messages": [HumanMessage(content=user_message)],
        "thread_id": thread_id,
        # The checkpoint retains older turns for context, but the tool budget
        # is independent for each new user request.
        "tool_rounds": 0,
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
            elif kind == "on_chain_end" and (event.get("name") == "execute_tools" or graph_node == "execute_tools"):
                output_data = data.get("output", {})
                tool_messages = output_data.get("messages", []) if isinstance(output_data, dict) else []
                citations = []
                for tool_message in tool_messages:
                    evidence = getattr(tool_message, "additional_kwargs", {}) or {}
                    if evidence.get("evidence_type") == "web":
                        citations.extend(
                            {
                                "title": source.get("title"),
                                "source": source.get("source"),
                                "url": source.get("url"),
                                "detail": source.get("excerpt"),
                                "retrieved_at": source.get("retrieved_at"),
                                "relevance_score": source.get("relevance_score"),
                            }
                            for source in evidence.get("sources", [])
                            if source.get("url")
                        )
                        continue
                    if evidence.get("rows_available") is None:
                        continue
                    columns = evidence.get("referenced_columns", [])
                    citations.append({
                        "title": "Uploaded workbook",
                        "source": f"{agent.get_dataset_context(thread_id).schema.get('filename', 'Workbook')} · {', '.join(columns) if columns else 'worksheet rows'}",
                        "detail": f"{evidence.get('rows_examined', evidence['rows_available']):,} of {evidence['rows_available']:,} rows estimated from code · {len(columns)} column(s) referenced",
                    })
                if citations:
                    yield _sse({"event": "citations", "citations": citations})
            elif kind == "on_chain_end" and (event.get("name") == "run_evaluation" or graph_node == "run_evaluation"):
                output_data = data.get("output", {})
                if isinstance(output_data, dict):
                    result = output_data.get("structured_response")
                    if result is not None:
                        if hasattr(result, "model_dump"):
                            result = result.model_dump()
                        if isinstance(result, dict) and result.get("assistant_message"):
                            yield _sse({"event": "final_answer", "text": result["assistant_message"]})
                        metrics = result.get("evaluation_metrics", {}) if isinstance(result, dict) else {}
                        conf = metrics.get("confidence_score") if isinstance(metrics, dict) else None
                        yield _sse({
                            "event": "evaluation",
                            "confidence_score": conf,
                            "payload": result,
                        })
                        yield _sse({"event": "metrics_evaluation", "payload": result})
    except Exception:
        logger.exception("Data-agent stream failed for session %s", agent._fingerprint(thread_id))
        yield _sse(
            {
                "event": "error",
                "details": "The data assistant failed. Check the server log for details.",
            }
        )
    finally:
        stream_ms = round((time.perf_counter() - stream_start) * 1000, 2)
        logger.info("LATENCY data_agent.stream: %.2fms", stream_ms, extra={
            "audit": {
                "action": "chat_stream_completed",
                "session": agent._fingerprint(thread_id),
                "duration_ms": stream_ms,
            }
        })
        yield _sse({"event": "latency", "total_ms": stream_ms})
        logger.info("Data-agent stream closed for session %s", agent._fingerprint(thread_id))
        yield _sse("[DONE]")
