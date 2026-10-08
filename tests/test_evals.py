import unittest

from evals.metrics import (
    pipeline_quality_matrix,
    routing_matrix,
    throughput_matrix,
)


class EvaluationMatricesTests(unittest.TestCase):
    def test_pipeline_quality_matrix_calculates_means_and_pass_rate(self):
        documents = [
            {
                "classification_confidence": 0.95,
                "extraction": {
                    "document_type": "AADHAAR_CARD",
                    "aadhaar_data": {
                        "aadhaar_number": {"final_field_score": 0.92},
                        "name": {"final_field_score": 0.88},
                    },
                    "system_evaluation_matrix": {"validation_failures": []},
                },
            },
            {
                "classification_confidence": 0.85,
                "extraction": {
                    "document_type": "PAN_CARD",
                    "pan_data": {
                        "pan_number": {"final_field_score": 0.90},
                    },
                    "system_evaluation_matrix": {
                        "validation_failures": ["dob_invalid"],
                    },
                },
            },
        ]

        matrix = pipeline_quality_matrix(documents)
        self.assertEqual(matrix["classification"]["count"], 2)
        self.assertEqual(matrix["classification"]["mean"], 0.9)
        self.assertEqual(matrix["field_confidence"]["count"], 3)
        self.assertAlmostEqual(matrix["field_confidence"]["mean"], 0.9, places=2)
        self.assertEqual(matrix["validation_pass_rate"], 0.5)

    def test_throughput_matrix_calculates_pages_per_second(self):
        matrix = throughput_matrix(10, 2000.0, {"segmentation": 200.0, "export": 300.0})
        self.assertEqual(matrix["total_pages"], 10)
        self.assertEqual(matrix["total_ms"], 2000.0)
        self.assertEqual(matrix["avg_ms_per_page"], 200.0)
        self.assertEqual(matrix["pages_per_second"], 5.0)
        self.assertEqual(matrix["stage_breakdown_ms"]["segmentation"], 200.0)

    def test_routing_matrix_computes_automation_rate_and_reasons(self):
        documents = [
            {
                "document_type": "AADHAAR_CARD",
                "extraction": {
                    "system_evaluation_matrix": {
                        "final_routing_decision": "AUTOMATED_PROCESSING"
                    }
                },
            },
            {
                "document_type": "PAN_CARD",
                "extraction": {
                    "system_evaluation_matrix": {
                        "final_routing_decision": "HUMAN_REVIEW_REQUIRED"
                    }
                },
            },
        ]
        review_report = {
            "flagged_fields": [
                {"reason": "low_confidence"},
                {"reason": "low_confidence"},
                {"reason": "validation_failure"},
            ],
            "human_review_required": True,
        }

        matrix = routing_matrix(documents, review_report)
        self.assertEqual(matrix["document_types"]["AADHAAR_CARD"], 1)
        self.assertEqual(matrix["document_types"]["PAN_CARD"], 1)
        self.assertEqual(matrix["automation_rate"], 0.5)
        self.assertEqual(matrix["total_flags"], 3)
        self.assertEqual(matrix["flags_by_reason"]["low_confidence"], 2)
        self.assertEqual(matrix["flags_by_reason"]["validation_failure"], 1)
        self.assertTrue(matrix["human_review_required"])


if __name__ == "__main__":
    unittest.main()
