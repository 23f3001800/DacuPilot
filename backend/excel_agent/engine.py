import ast
import contextlib
import io
import multiprocessing
import os
import operator
import queue
from typing import Any

MAX_CODE_LENGTH = 12000
MAX_EXECUTION_SECONDS = 5
MAX_EXECUTION_MEMORY_HEADROOM_BYTES = 2 * 1024 * 1024 * 1024
MAX_OUTPUT_CHARS = 20000

_BLOCKED_NAMES = {
    "__import__", "eval", "exec", "compile", "open", "input", "help",
    "dir", "vars", "getattr", "setattr", "delattr", "globals", "locals",
}
_BLOCKED_ATTRIBUTES = {
    "read_csv", "read_excel", "read_json", "read_pickle", "read_parquet",
    "read_sql", "read_sql_query", "read_sql_table", "to_csv", "to_excel",
    "to_pickle", "to_parquet", "to_sql", "to_json", "to_hdf", "to_feather",
}
_DATAFRAME_PROPERTIES = {"columns", "dtypes", "shape", "index", "empty", "size", "ndim"}
_SERIES_PROPERTIES = {"name", "dtype", "shape", "index", "empty", "size", "ndim"}
_DATAFRAME_METHODS = {
    "abs", "agg", "all", "any", "corr", "count", "describe", "diff",
    "drop", "drop_duplicates", "dropna", "duplicated", "fillna", "groupby",
    "head", "idxmax", "idxmin", "isna", "max", "mean", "median", "min",
    "nlargest", "nsmallest", "notna", "nunique", "pct_change", "pivot_table",
    "quantile", "rank", "rename", "replace", "reset_index", "round", "select_dtypes",
    "shift", "sort_index", "sort_values", "std", "sum", "tail", "transpose", "var",
    "value_counts",
}
_SERIES_METHODS = _DATAFRAME_METHODS | {
    "between", "clip", "cummax", "cummin", "cumsum", "isin", "unique", "where", "mask",
}
_INDEX_METHODS = {"astype", "nunique", "sort_values", "tolist", "unique", "value_counts"}
_GROUPBY_METHODS = {
    "agg", "all", "any", "count", "first", "last", "max", "mean", "median", "min",
    "nunique", "size", "std", "sum", "var", "value_counts",
}
_SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}
_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.BitAnd: operator.and_,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
_COMPARE_OPERATORS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
}


class _SafeMethod:
    def __init__(self, target: Any, name: str):
        self.target = target
        self.name = name


class _SafeEvaluator:
    """Evaluate a small Pandas analysis language without Python exec/eval."""

    def __init__(self, data_frame: Any, output: io.StringIO):
        import pandas as pd
        from pandas.core.groupby.generic import DataFrameGroupBy, SeriesGroupBy

        self.pd = pd
        self.data_frame_type = pd.DataFrame
        self.series_type = pd.Series
        self.groupby_types = (DataFrameGroupBy, SeriesGroupBy)
        self.output = output
        self.print_function = self._print
        self.environment = {"df": data_frame, **_SAFE_BUILTINS, "print": self.print_function}

    def _format(self, value: Any) -> str:
        if isinstance(value, self.data_frame_type):
            with self.pd.option_context("display.max_rows", 50, "display.max_columns", 30, "display.width", 180):
                return value.head(50).to_string(max_rows=50, max_cols=30)
        if isinstance(value, self.series_type):
            with self.pd.option_context("display.max_rows", 100, "display.width", 180):
                return value.head(100).to_string(max_rows=100)
        if isinstance(value, dict):
            items = list(value.items())
            rendered = str(dict(items[:100]))
            return rendered + (" … (truncated)" if len(items) > 100 else "")
        if isinstance(value, (list, tuple, set)):
            items = list(value)
            rendered = str(items[:100])
            return rendered + (" … (truncated)" if len(items) > 100 else "")
        return str(value)

    def _print(self, *values: Any, sep: str = " ", end: str = "\n") -> None:
        if not isinstance(sep, str) or not isinstance(end, str):
            raise TypeError("print sep and end must be strings")
        remaining = MAX_OUTPUT_CHARS - self.output.tell()
        if remaining <= 0:
            return
        text = sep.join(self._format(value) for value in values) + end
        self.output.write(text[:remaining])

    def _attribute(self, target: Any, name: str) -> Any:
        if name.startswith("_") or name in _BLOCKED_ATTRIBUTES:
            raise ValueError("Attribute is blocked by sandbox safety policies.")
        if isinstance(target, self.data_frame_type):
            allowed_properties = _DATAFRAME_PROPERTIES | {"loc", "iloc"}
            if name in allowed_properties:
                return getattr(target, name)
            if name in _DATAFRAME_METHODS:
                return _SafeMethod(target, name)
        elif isinstance(target, self.series_type):
            allowed_properties = _SERIES_PROPERTIES | {"loc", "iloc"}
            if name in allowed_properties:
                return getattr(target, name)
            if name in _SERIES_METHODS:
                return _SafeMethod(target, name)
        elif isinstance(target, self.groupby_types) and name in _GROUPBY_METHODS:
            return _SafeMethod(target, name)
        elif isinstance(target, self.pd.Index):
            if name in {"dtype", "name", "shape", "size", "is_unique"}:
                return getattr(target, name)
            if name in _INDEX_METHODS:
                return _SafeMethod(target, name)
        raise ValueError(f"Attribute '{name}' is blocked by sandbox safety policies.")

    def _call(self, function: Any, args: list[Any], kwargs: dict[str, Any]) -> Any:
        if isinstance(function, _SafeMethod):
            if kwargs.get("inplace") is True:
                raise ValueError("In-place workbook changes are blocked by sandbox safety policies.")
            kwargs.pop("inplace", None)
            if function.name == "groupby" and kwargs.get("as_index") is False:
                kwargs.pop("as_index")
            return getattr(function.target, function.name)(*args, **kwargs)
        if function is self.print_function:
            return function(*args, **kwargs)
        if function in _SAFE_BUILTINS.values():
            return function(*args, **kwargs)
        raise ValueError("Function calls are blocked by sandbox safety policies.")

    def _assign(self, name: str, value: Any) -> None:
        if name == "df" or name in _SAFE_BUILTINS or name == "print":
            raise ValueError("Rebinding protected sandbox names is blocked by sandbox safety policies.")
        self.environment[name] = value

    def evaluate(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in _BLOCKED_NAMES:
                raise ValueError("Call is blocked by sandbox safety policies.")
            if node.id not in self.environment:
                raise NameError(f"name '{node.id}' is not defined")
            return self.environment[node.id]
        if isinstance(node, ast.List):
            return [self.evaluate(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(self.evaluate(item) for item in node.elts)
        if isinstance(node, ast.Set):
            return {self.evaluate(item) for item in node.elts}
        if isinstance(node, ast.Dict):
            return {self.evaluate(key): self.evaluate(value) for key, value in zip(node.keys, node.values)}
        if isinstance(node, ast.Attribute):
            return self._attribute(self.evaluate(node.value), node.attr)
        if isinstance(node, ast.Subscript):
            target = self.evaluate(node.value)
            key = self.evaluate(node.slice)
            safe_container = isinstance(target, (self.data_frame_type, self.series_type, dict, list, tuple, str)) or isinstance(target, self.groupby_types)
            safe_indexer = type(target).__module__.startswith("pandas.core.indexing")
            if not safe_container and not safe_indexer:
                raise ValueError("Indexing this value is blocked by sandbox safety policies.")
            return target[key]
        if isinstance(node, ast.Slice):
            return slice(self.evaluate(node.lower) if node.lower else None,
                         self.evaluate(node.upper) if node.upper else None,
                         self.evaluate(node.step) if node.step else None)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
            right = self.evaluate(node.right)
            left = self.evaluate(node.left)
            if isinstance(node.op, ast.Pow) and isinstance(right, (int, float)) and abs(right) > 10:
                raise ValueError("Exponents above 10 are blocked by sandbox resource limits.")
            return _BINARY_OPERATORS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
            return _UNARY_OPERATORS[type(node.op)](self.evaluate(node.operand))
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1:
                raise ValueError("Chained comparisons are unsupported; combine comparisons with '&' or '|'.")
            operation = _COMPARE_OPERATORS.get(type(node.ops[0]))
            if operation is None:
                raise ValueError("Comparison is blocked by sandbox safety policies.")
            return operation(self.evaluate(node.left), self.evaluate(node.comparators[0]))
        if isinstance(node, ast.BoolOp):
            values = [bool(self.evaluate(value)) for value in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.IfExp):
            return self.evaluate(node.body if self.evaluate(node.test) else node.orelse)
        if isinstance(node, ast.JoinedStr):
            return "".join(self._format(value.value) if isinstance(value, ast.FormattedValue)
                           else str(self.evaluate(value)) for value in node.values)
        if isinstance(node, ast.FormattedValue):
            value = self.evaluate(node.value)
            if node.conversion == ord("r"):
                value = repr(value)
            elif node.conversion == ord("a"):
                value = ascii(value)
            elif node.format_spec is not None:
                value = format(value, self.evaluate(node.format_spec))
            else:
                value = self._format(value)
            return value
        if isinstance(node, ast.Call):
            if any(keyword.arg is None for keyword in node.keywords):
                raise ValueError("Expanded keyword arguments are blocked by sandbox safety policies.")
            function = self.evaluate(node.func)
            args = [self.evaluate(argument) for argument in node.args]
            kwargs = {keyword.arg: self.evaluate(keyword.value) for keyword in node.keywords}
            return self._call(function, args, kwargs)
        raise ValueError(f"Python syntax '{type(node).__name__}' is blocked by sandbox safety policies.")

    def run(self, code: str) -> None:
        tree = ast.parse(code, mode="exec")
        for statement in tree.body:
            if isinstance(statement, ast.Assign):
                if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
                    raise ValueError("Only assigning a result to a variable is supported.")
                name = statement.targets[0].id
                self._assign(name, self.evaluate(statement.value))
            elif isinstance(statement, ast.Expr):
                self.evaluate(statement.value)
            elif isinstance(statement, ast.Assert):
                if not bool(self.evaluate(statement.test)):
                    raise AssertionError("The generated result validation assertion failed.")
            elif isinstance(statement, ast.If):
                branch = statement.body if bool(self.evaluate(statement.test)) else statement.orelse
                for nested in branch:
                    if isinstance(nested, ast.Expr):
                        self.evaluate(nested.value)
                    elif isinstance(nested, ast.Assert):
                        if not bool(self.evaluate(nested.test)):
                            raise AssertionError("The generated result validation assertion failed.")
                    elif isinstance(nested, ast.Assign) and len(nested.targets) == 1 and isinstance(nested.targets[0], ast.Name):
                        self._assign(nested.targets[0].id, self.evaluate(nested.value))
                    else:
                        raise ValueError("Nested statement is blocked by sandbox safety policies.")
            else:
                raise ValueError(f"Python statement '{type(statement).__name__}' is blocked by sandbox safety policies.")


def _execute_in_child(code: str, data_frame: Any, result_queue: Any) -> None:
    try:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (MAX_EXECUTION_SECONDS, MAX_EXECUTION_SECONDS + 1))
        except (ImportError, AttributeError, OSError, ValueError):
            pass
        try:
            import resource
            if hasattr(resource, "RLIMIT_AS"):
                soft, hard = resource.getrlimit(resource.RLIMIT_AS)
                # RLIMIT_AS counts all mapped address space, including Python,
                # pandas, NumPy, and the deserialized workbook. Bound additional
                # worker allocation above that baseline instead of imposing a
                # total cap smaller than the already-loaded runtime.
                with open("/proc/self/statm", encoding="ascii") as statm:
                    virtual_pages = int(statm.read().split()[0])
                current_virtual_bytes = virtual_pages * os.sysconf("SC_PAGE_SIZE")
                requested_limit = current_virtual_bytes + MAX_EXECUTION_MEMORY_HEADROOM_BYTES
                hard_limit = (
                    requested_limit
                    if hard == resource.RLIM_INFINITY
                    else min(hard, requested_limit)
                )
                soft_limit = hard_limit if soft == resource.RLIM_INFINITY else min(soft, hard_limit)
                resource.setrlimit(resource.RLIMIT_AS, (soft_limit, hard_limit))
        except (ImportError, AttributeError, OSError, ValueError):
            pass
        output_buffer = io.StringIO()
        with contextlib.redirect_stdout(output_buffer):
            _SafeEvaluator(data_frame, output_buffer).run(code)
        output = output_buffer.getvalue()
        result_queue.put(output if output.strip() else "Code executed successfully with no print output.")
    except Exception as exc:
        result_queue.put(f"ERROR during execution: {type(exc).__name__}: {exc}")


class PythonSandboxREPL:
    def __init__(self, data_frame):
        self.data_frame = data_frame

    def _validate_code(self, clean_code: str) -> str | None:
        if len(clean_code) > MAX_CODE_LENGTH:
            return f"ERROR: Generated code exceeds the maximum allowed length ({MAX_CODE_LENGTH} characters)."
        try:
            tree = ast.parse(clean_code, mode="exec")
        except SyntaxError as exc:
            return f"ERROR: Invalid Python syntax: {exc.msg}."
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                return "ERROR: Syntax is blocked by sandbox safety policies."
            if isinstance(node, ast.Name) and node.id in _BLOCKED_NAMES:
                return "ERROR: Call is blocked by sandbox safety policies."
            if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in _BLOCKED_ATTRIBUTES):
                return "ERROR: Attribute is blocked by sandbox safety policies."
        return None

    def execute_code(self, code_string: str) -> str:
        """Run the supported Pandas expression subset in a timed child process."""
        clean_code = code_string.replace("```python", "").replace("```", "").strip()
        validation_error = self._validate_code(clean_code)
        if validation_error:
            return validation_error

        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue()
        process = context.Process(target=_execute_in_child, args=(clean_code, self.data_frame, result_queue))
        process.daemon = True
        process.start()
        process.join(MAX_EXECUTION_SECONDS)
        if process.is_alive():
            process.terminate()
            process.join()
            result_queue.close()
            return f"ERROR: Execution timed out after {MAX_EXECUTION_SECONDS} seconds."
        if process.exitcode not in (0, None):
            result_queue.close()
            return (
                "ERROR: The isolated analysis worker stopped unexpectedly "
                f"(exit code {process.exitcode}); the result was not applied."
            )
        try:
            return result_queue.get(timeout=0.5)
        except queue.Empty:
            return "ERROR during execution: Child process returned no result."
        finally:
            result_queue.close()


def evaluate_dataframe_expression(expression: str, data_frame: Any) -> Any:
    """Evaluate a validated single expression without Python's eval function."""
    if len(expression) > 500:
        raise ValueError("Formula exceeds the maximum allowed length (500 characters).")
    tree = ast.parse(expression, mode="eval")
    return _SafeEvaluator(data_frame, io.StringIO()).evaluate(tree.body)
