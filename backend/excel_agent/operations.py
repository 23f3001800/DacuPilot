import ast
import re
from dataclasses import dataclass
from uuid import uuid4

import pandas as pd
from pydantic import BaseModel, Field


class ColumnOperationRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    column_name: str = Field(min_length=1, max_length=100)
    formula: str = Field(min_length=1, max_length=500)


class PendingColumnOperation:
    def __init__(self, thread_id: str, column_name: str, formula: str, frame: pd.DataFrame):
        self.operation_id = uuid4().hex
        self.thread_id = thread_id
        self.column_name = column_name
        self.formula = formula
        self.frame = frame


_pending: dict[str, PendingColumnOperation] = {}


def _validate_formula(formula: str, columns: list[str]) -> None:
    tree = ast.parse(formula, mode="eval")
    allowed_columns = set(columns)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Call, ast.Attribute, ast.Lambda, ast.Import, ast.ImportFrom)):
            raise ValueError("Formula calls, attributes, and imports are not allowed.")
        if isinstance(node, ast.Name) and node.id not in allowed_columns and node.id != "df":
            raise ValueError(f"Formula references unknown column '{node.id}'.")
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
    result = eval(compile(ast.parse(formula, mode="eval"), "<column-formula>", "eval"),
                  {"__builtins__": {}, "df": frame}, {})
    if isinstance(result, pd.DataFrame):
        raise ValueError("Formula must return one value per row, not a dataframe.")
    if not isinstance(result, pd.Series):
        result = pd.Series([result] * len(frame), index=frame.index)
    return result


def preview_operation(thread_id: str, frame: pd.DataFrame, column_name: str, formula: str) -> dict:
    if column_name in frame.columns:
        raise ValueError(f"Column '{column_name}' already exists.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]{0,99}", column_name):
        raise ValueError("Column name contains unsupported characters.")
    values = _evaluate(frame.copy(), formula)
    pending = PendingColumnOperation(thread_id, column_name, formula, frame.copy())
    _pending[pending.operation_id] = pending
    before = frame.head(5).to_dict(orient="records")
    after_frame = frame.copy()
    after_frame[column_name] = values
    after = after_frame.head(5).to_dict(orient="records")
    return {"operation_id": pending.operation_id, "column_name": column_name,
            "formula": formula, "before": before, "after": after}


def apply_operation(operation_id: str, thread_id: str) -> tuple[str, pd.DataFrame, str]:
    pending = _pending.pop(operation_id, None)
    if pending is None or pending.thread_id != thread_id:
        raise ValueError("Column operation is missing, expired, or belongs to another session.")
    values = _evaluate(pending.frame.copy(), pending.formula)
    updated = pending.frame.copy()
    updated[pending.column_name] = values
    return pending.column_name, updated, pending.formula
