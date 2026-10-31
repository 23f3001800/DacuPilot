import sys
import ast
import io
import contextlib

MAX_CODE_LENGTH = 12000
_BLOCKED_NAMES = {
    "__import__", "eval", "exec", "compile", "open", "input", "help",
    "dir", "vars", "getattr", "setattr", "delattr", "globals", "locals",
}
_BLOCKED_ATTRIBUTES = {
    "read_csv", "read_excel", "read_json", "read_pickle", "read_parquet",
    "read_sql", "read_sql_query", "read_sql_table", "to_csv", "to_excel",
}

class PythonSandboxREPL:
    def __init__(self, data_frame):
        # Bind the live dataframe inside the sandbox context
        self.globals = {"pd": sys.modules['pandas'], "df": data_frame}
        self.locals = {}

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
        } | set(self.locals) | assigned_names

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                return "ERROR: Imports are not allowed in spreadsheet analysis code."
            if isinstance(node, ast.Name) and node.id not in allowed_names:
                return f"ERROR: Name '{node.id}' is not allowed in spreadsheet analysis code."
            if isinstance(node, ast.Attribute):
                if node.attr.startswith("__") or node.attr in _BLOCKED_ATTRIBUTES:
                    return f"ERROR: Attribute '{node.attr}' is restricted."
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_NAMES:
                    return f"ERROR: Call '{node.func.id}' is restricted."

    def execute_code(self, code_string: str) -> str:
        """Executes Python code and captures text printed to stdout."""
        # Clean markdown formatting wraps if the LLM adds them
        clean_code = code_string.replace("```python", "").replace("```", "").strip()

        validation_error = self._validate_code(clean_code)
        if validation_error:
            return validation_error
        
        stdout_buffer = io.StringIO()
        
        try:
            # Catch standard output prints
            with contextlib.redirect_stdout(stdout_buffer):
                exec(clean_code, self.globals, self.locals)
            output = stdout_buffer.getvalue()
            return output if output.strip() else "Code executed successfully with no print output."
        except Exception as e:
            # Return error strings back to the LLM so it can rewrite its query
            return f"ERROR during execution: {type(e).__name__}: {str(e)}"
