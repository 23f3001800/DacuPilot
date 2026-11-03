import ast
import re
import threading
import time
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import pandas as pd
from pydantic import BaseModel, Field

from .engine import evaluate_dataframe_expression


class ColumnOperationRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    column_name: str = Field(min_length=1, max_length=100)
    operation: Literal["add", "update", "delete"] = "add"
    formula: str | None = Field(default=None, max_length=500)


class PendingColumnOperation:
    def __init__(self, thread_id: str, operation: str, column_name: str, formula: str | None, frame: pd.DataFrame, source_revision: str | None):
        self.operation_id = uuid4().hex
        self.thread_id = thread_id
        self.operation = operation
        self.column_name = column_name
        self.formula = formula
        self.frame = frame
        self.source_revision = source_revision
        self.expires_at = time.monotonic() + 600


_pending: dict[str, PendingColumnOperation] = {}
_pending_lock = threading.RLock()
MAX_PENDING_COLUMN_OPERATIONS = 4


def _prune_pending() -> None:
    now = time.monotonic()
    for operation_id, operation in list(_pending.items()):
        if operation.expires_at <= now:
            _pending.pop(operation_id, None)


def clear_pending_operations(thread_id: str) -> None:
    with _pending_lock:
        for operation_id, operation in list(_pending.items()):
            if operation.thread_id == thread_id:
                _pending.pop(operation_id, None)


def _validate_formula(formula: str, columns: list[str]) -> None:
    tree = ast.parse(formula, mode="eval")
    allowed_columns = set(columns)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Call, ast.Attribute, ast.Lambda, ast.Import, ast.ImportFrom)):
            raise ValueError("Formula calls, attributes, and imports are not allowed.")
        if isinstance(node, ast.Name) and node.id not in allowed_columns and node.id != "df":
            raise ValueError(f"Formula references unknown column '{node.id}'.")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exponent = node.right
            if isinstance(exponent, ast.Constant) and isinstance(exponent.value, (int, float)) and abs(exponent.value) > 10:
                raise ValueError("Formula exponents above 10 are not supported.")
        if isinstance(node, ast.Subscript):
            if not isinstance(node.value, ast.Name) or node.value.id != "df":
                raise ValueError("Only df['Column'] references are allowed in formulas.")
            if not isinstance(node.slice, ast.Constant) or node.slice.value not in allowed_columns:
                raise ValueError("Formula references an unknown dataframe column.")
        if not isinstance(node, (ast.Expression, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
                                 ast.Pow, ast.Mod, ast.USub, ast.UAdd, ast.Name, ast.Load,
                                 ast.Constant, ast.Subscript, ast.FloorDiv, ast.MatMult,
                                 ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift,
                                 ast.Compare, ast.Gt, ast.GtE, ast.Lt, ast.LtE, ast.Eq,
                                 ast.NotEq, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp)):
            raise ValueError("Formula contains an unsupported expression.")


def _evaluate(frame: pd.DataFrame, formula: str) -> pd.Series:
    _validate_formula(formula, [str(column) for column in frame.columns])
    result = evaluate_dataframe_expression(formula, frame)
    if isinstance(result, pd.DataFrame):
        raise ValueError("Formula must return one value per row, not a dataframe.")
    if not isinstance(result, pd.Series):
        result = pd.Series([result] * len(frame), index=frame.index)
    return result


def preview_operation(
    thread_id: str,
    frame: pd.DataFrame,
    column_name: str,
    formula: str | None,
    source_revision: str | None = None,
    operation: str = "add",
) -> dict:
    if operation not in {"add", "update", "delete"}:
        raise ValueError("Choose add, update, or delete for a column change.")
    if not column_name or len(column_name) > 100:
        raise ValueError("Column name must contain between 1 and 100 characters.")
    if operation == "add" and not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]{0,99}", column_name):
        raise ValueError("Column name contains unsupported characters.")
    if operation == "add" and column_name in frame.columns:
        raise ValueError(f"Column '{column_name}' already exists. Use update to change it.")
    if operation in {"update", "delete"} and column_name not in frame.columns:
        raise ValueError(f"Column '{column_name}' does not exist in this workbook.")
    if operation == "delete" and len(frame.columns) <= 1:
        raise ValueError("The last remaining workbook column cannot be deleted.")
    if operation == "delete" and formula:
        raise ValueError("A delete preview does not take a formula.")
    if operation != "delete" and not formula:
        raise ValueError("Add and update previews require a formula.")

    before = frame.head(5).to_dict(orient="records")
    if operation == "delete":
        values = None
        after_frame = frame.drop(columns=[column_name]).copy()
        rows_evaluated = len(frame)
        populated_rows = None
        result_coverage = None
    else:
        values = _evaluate(frame.copy(), formula)
        rows_evaluated = len(values)
        populated_rows = int(values.notna().sum())
        result_coverage = round(populated_rows / rows_evaluated * 100, 2) if rows_evaluated else 0.0
        after_frame = frame.copy()
        after_frame[column_name] = values
    after = after_frame.head(5).to_dict(orient="records")
    with _pending_lock:
        _prune_pending()
        if sum(item.thread_id == thread_id for item in _pending.values()) >= 2 or len(_pending) >= MAX_PENDING_COLUMN_OPERATIONS:
            raise ValueError("Too many pending workbook previews. Apply or discard an existing preview first.")
        pending = PendingColumnOperation(thread_id, operation, column_name, formula, frame.copy(), source_revision)
        _pending[pending.operation_id] = pending
    return {
        "operation_id": pending.operation_id,
        "operation": operation,
        "column_name": column_name,
        "formula": formula,
        "before": before,
        "after": after,
        "validation": {
            "rows_evaluated": rows_evaluated,
            "populated_rows": populated_rows,
            "result_coverage_percentage": result_coverage,
            "affected_rows": rows_evaluated if operation == "delete" else None,
        },
    }


def apply_operation(operation_id: str, thread_id: str, source_revision: str | None = None) -> tuple[str, pd.DataFrame, str | None, str]:
    with _pending_lock:
        _prune_pending()
        pending = _pending.pop(operation_id, None)
    if pending is None or pending.thread_id != thread_id:
        raise ValueError("Column operation is missing, expired, or belongs to another session.")
    if pending.source_revision != source_revision:
        raise ValueError("The workbook changed after this preview. Create a new preview before applying it.")
    updated = pending.frame.copy()
    if pending.operation == "delete":
        updated = updated.drop(columns=[pending.column_name])
    else:
        values = _evaluate(updated, pending.formula or "")
        updated[pending.column_name] = values
    return pending.column_name, updated, pending.formula, pending.operation
