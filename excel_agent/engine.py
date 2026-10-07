import sys
import io
import contextlib

class PythonSandboxREPL:
    def __init__(self, data_frame):
        # Bind the live dataframe inside the sandbox context
        self.globals = {"pd": sys.modules['pandas'], "df": data_frame}
        self.locals = {}

    def execute_code(self, code_string: str) -> str:
        """Executes Python code and captures text printed to stdout."""
        # Clean markdown formatting wraps if the LLM adds them
        clean_code = code_string.replace("```python", "").replace("```", "").strip()
        
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
