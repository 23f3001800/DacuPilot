import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import Workbook

from excel_agent.loader import load_real_world_excel


WORKBOOK = (
    Path(__file__).resolve().parents[2]
    / "excel_agent"
    / "Inventory-Records-Sample-Data.xlsx"
)


class ExcelLoaderTests(unittest.TestCase):
    def test_finds_table_beneath_title_rows(self):
        dataframe, schema = load_real_world_excel(str(WORKBOOK))

        self.assertEqual(len(dataframe.columns), 8)
        self.assertEqual(schema["total_rows"], 46)
        self.assertIn("Product ID", schema["columns"])
        self.assertIn("Hand-In-\nStock", schema["columns"])

    def test_reads_expected_sample_record(self):
        dataframe, _ = load_real_world_excel(str(WORKBOOK))

        product = dataframe.loc[dataframe["Product Name"] == "Smartphone"].iloc[0]
        self.assertEqual(product["Hand-In-\nStock"], 80)

    def test_rejects_workbooks_over_the_cell_budget_before_full_loading(self):
        with TemporaryDirectory() as temporary_directory:
            workbook_path = Path(temporary_directory) / "wide.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["A", "B"])
            sheet.append([1, 2])
            sheet.append([3, 4])
            workbook.save(workbook_path)

            with patch("excel_agent.loader.MAX_WORKBOOK_CELLS", 2):
                with self.assertRaisesRegex(ValueError, "2-cell analysis limit"):
                    load_real_world_excel(str(workbook_path))


if __name__ == "__main__":
    unittest.main()
