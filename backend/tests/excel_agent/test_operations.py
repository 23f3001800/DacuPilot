import unittest

import pandas as pd

from excel_agent.operations import apply_operation, clear_pending_operations, preview_operation


class ColumnOperationTests(unittest.TestCase):
    def setUp(self):
        self.thread_id = "00000000-0000-4000-8000-000000000041"
        self.frame = pd.DataFrame({"item": ["pen", "book"], "quantity": [2, 5]})

    def tearDown(self):
        clear_pending_operations(self.thread_id)

    def test_adds_a_new_column_after_preview_and_apply(self):
        preview = preview_operation(
            self.thread_id,
            self.frame,
            "double quantity",
            "df['quantity'] * 2",
            "revision-1",
        )

        self.assertEqual(preview["operation"], "add")
        self.assertNotIn("double quantity", self.frame.columns)

        name, updated, formula, operation = apply_operation(
            preview["operation_id"], self.thread_id, "revision-1"
        )

        self.assertEqual((name, formula, operation), ("double quantity", "df['quantity'] * 2", "add"))
        self.assertEqual(updated["double quantity"].tolist(), [4, 10])

    def test_updates_an_existing_column_only_after_apply(self):
        preview = preview_operation(
            self.thread_id,
            self.frame,
            "quantity",
            "df['quantity'] * 2",
            "revision-1",
            "update",
        )

        self.assertEqual(preview["operation"], "update")
        self.assertEqual(preview["before"][0]["quantity"], 2)
        self.assertEqual(preview["after"][0]["quantity"], 4)
        self.assertEqual(self.frame["quantity"].tolist(), [2, 5])

        name, updated, formula, operation = apply_operation(
            preview["operation_id"], self.thread_id, "revision-1"
        )

        self.assertEqual((name, formula, operation), ("quantity", "df['quantity'] * 2", "update"))
        self.assertEqual(updated["quantity"].tolist(), [4, 10])

    def test_deletes_an_existing_column_only_after_apply(self):
        preview = preview_operation(
            self.thread_id,
            self.frame,
            "quantity",
            None,
            "revision-1",
            "delete",
        )

        self.assertEqual(preview["operation"], "delete")
        self.assertIn("quantity", preview["before"][0])
        self.assertNotIn("quantity", preview["after"][0])
        self.assertIn("quantity", self.frame.columns)

        name, updated, formula, operation = apply_operation(
            preview["operation_id"], self.thread_id, "revision-1"
        )

        self.assertEqual((name, formula, operation), ("quantity", None, "delete"))
        self.assertEqual(list(updated.columns), ["item"])

    def test_rejects_deleting_the_last_column(self):
        with self.assertRaisesRegex(ValueError, "last remaining"):
            preview_operation(
                self.thread_id,
                self.frame[["item"]],
                "item",
                None,
                "revision-1",
                "delete",
            )


if __name__ == "__main__":
    unittest.main()
