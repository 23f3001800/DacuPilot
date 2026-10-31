import sys
import ast
import io
import contextlib
import multiprocessing
import queue
from typing import Any

MAX_CODE_LENGTH = 12000
MAX_EXECUTION_SECONDS = 5
_BLOCKED_NAMES = {
    "__import__", "eval", "exec", "compile", "open", "input", "help",
    "dir", "vars", "getattr", "setattr", "delattr", "globals", "locals",
}
_BLOCKED_ATTRIBUTES = {
    "read_csv", "read_excel", "read_json", "read_pickle", "read_parquet",
    "read_sql", "read_sql_query", "read_sql_table", "to_csv", "to_excel",
}


def _execute_in_child(code: str, data_frame: Any, result_queue: Any) -> None:
    try:
        import builtins
        import pandas as pd

        allowed_builtins = {
            name: getattr(builtins, name)
            for name in (
                "abs", "all", "any", "bool", "dict", "enumerate", "float",
                "int", "len", "list", "max", "min", "print", "range",
                "round", "set", "sorted", "str", "sum", "tuple", "zip",
            )
            if hasattr(builtins, name)
        }
        stdout_buffer = io.StringIO()
        sandbox_globals = {
            "__builtins__": allowed_builtins,
            "pd": pd,
            "df": data_frame,
        }
        with contextlib.redirect_stdout(stdout_buffer):
            exec(code, sandbox_globals, {})
        output = stdout_buffer.getvalue()
        result_queue.put(
            output if output.strip() else "Code executed successfully with no print output."
        )
    except Exception as exc:
        result_queue.put(f"ERROR during execution: {type(exc).__name__}: {exc}")

class PythonSandboxREPL:
    def __init__(self, data_frame):
        self.data_frame = data_frame

    def _validate_code(self, clean_code: str) -> str | None:
        if len(clean_code) > MAX_CODE_LENGTH:
            return (
                "ERROR: Generated code exceeds the maximum allowed length "
                f"({MAX_CODE_LENGTH} characters)."
            )

        try:
            tree = ast.parse(clean_code, mode="exec")
        except SyntaxError as exc:
            return f"ERROR: Invalid Python syntax: {exc.msg}."

        assigned_names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
        }
        allowed_names = {
            "df", "pd", "print", "len", "abs", "min", "max", "sum", "round",
            "sorted", "range", "str", "int", "float", "bool", "list", "dict",
            "set", "tuple", "enumerate", "zip", "any", "all", "True", "False",
            "None",
        } | assigned_names

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                return "ERROR: Imports are blocked by sandbox safety policies."
            if isinstance(node, ast.Attribute):
                if node.attr.startswith("__") or node.attr in _BLOCKED_ATTRIBUTES:
                    return "ERROR: Attribute is blocked by sandbox safety policies."
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_NAMES:
                    return "ERROR: Call is blocked by sandbox safety policies."

    def execute_code(self, code_string: str) -> str:
        """Executes Python code and captures text printed to stdout."""
        # Clean markdown formatting wraps if the LLM adds them
        clean_code = code_string.replace("```python", "").replace("```", "").strip()

        validation_error = self._validate_code(clean_code)
        if validation_error:
            return validation_error
        
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue()
        process = context.Process(
            target=_execute_in_child,
            args=(clean_code, self.data_frame, result_queue),
        )
        process.start()
        process.join(MAX_EXECUTION_SECONDS)
        if process.is_alive():
            process.terminate()
            process.join()
            return f"ERROR: Execution timed out after {MAX_EXECUTION_SECONDS} seconds."
        try:
            return result_queue.get_nowait()
        except queue.Empty:
            return "ERROR during execution: Child process returned no result."
