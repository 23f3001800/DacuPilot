import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
