import unittest

import pandas as pd

from excel_agent.engine import PythonSandboxREPL


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.repl = PythonSandboxREPL(
            pd.DataFrame({"item": ["pen", "book"], "quantity": [2, 5]})
        )

    def test_executes_dataframe_query_and_returns_printed_result(self):
        output = self.repl.execute_code(
            "print(df.loc[df['item'] == 'book', 'quantity'].sum())"
        )

        self.assertEqual(output.strip(), "5")

    def test_returns_execution_errors_instead_of_hiding_them(self):
        output = self.repl.execute_code("print(missing_variable)")

        self.assertIn("NameError", output)

    def test_blocks_dangerous_system_operations(self):
        dangerous_snippets = [
            "import os; os.system('whoami')",
            "import subprocess; subprocess.run(['ls'])",
            "open('/etc/passwd', 'r')",
            "import sys; sys.exit(1)",
        ]
        for snippet in dangerous_snippets:
            output = self.repl.execute_code(snippet)
            self.assertIn("blocked by sandbox safety policies", output)


if __name__ == "__main__":
    unittest.main()
