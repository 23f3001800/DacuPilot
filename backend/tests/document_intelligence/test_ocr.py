import os
import sys
import tempfile
import unittest
import types
from types import SimpleNamespace
from unittest.mock import patch

from datapilot.config import Config
from datapilot.config import AppConfig
from datapilot.llm_provider import create_openai_clients
from document_intelligence.schemas.documents import (
    AadhaarFields,
    BenefitIllustrationFields,
    DOCUMENT_DATA_FIELDS,
    DrivingLicenceFields,
    FatcaAnnexureFields,
    MasterDocumentIntelligencePayload,
    MoralHazardFields,
    MultiplePoliciesFields,
    NachMandateFields,
    PanFields,
    PassportFields,
    SuitabilityProfilerFields,
)
from document_intelligence.utils.ocr import MultimodalOCRProcessor
from document_intelligence.utils.google_document_ai import GoogleDocumentAIProcessor


class DocumentSchemaTests(unittest.TestCase):
    def test_all_ten_document_types_map_to_their_extraction_schema(self):
        expected = {
            "AADHAAR_CARD": (
                "aadhaar_data",
                AadhaarFields,
                {"aadhaar_number", "full_name", "date_of_birth", "address"},
            ),
            "PAN_CARD": (
                "pan_data",
                PanFields,
                {"pan_number", "full_name", "father_name", "date_of_birth"},
            ),
            "DRIVING_LICENCE": (
                "driving_licence_data",
                DrivingLicenceFields,
                {"dl_number", "name", "date_of_issue", "valid_till_date"},
            ),
            "PASSPORT": (
                "passport_data",
                PassportFields,
                {"passport_number", "date_of_birth", "date_of_expiry", "mrz_line_2"},
            ),
            "NACH_MANDATE": (
                "nach_mandate_data",
                NachMandateFields,
                {"bank_account_number", "ifsc_code", "bank_name", "amount_figures", "frequency"},
            ),
            "FATCA_ANNEXURE": (
                "fatca_annexure_data",
                FatcaAnnexureFields,
                {"policy_number", "tin_or_pan", "father_name", "place_of_birth", "nationality"},
            ),
            "BENEFIT_ILLUSTRATION": (
                "benefit_illustration_data",
                BenefitIllustrationFields,
                {"application_number", "policyholder_name", "date", "place"},
            ),
            "MORAL_HAZARD_QUESTIONNAIRE": (
                "moral_hazard_data",
                MoralHazardFields,
                {"application_number", "name_of_life_assured", "nominee_relationship", "date", "place"},
            ),
            "MULTIPLE_POLICIES_CONSENT": (
                "multiple_policies_data",
                MultiplePoliciesFields,
                {"proposer_name", "reason_for_multiple_policies", "date", "place"},
            ),
            "SUITABILITY_PROFILER": (
                "suitability_profiler_data",
                SuitabilityProfilerFields,
                {"application_number", "name_of_life_assured", "name_of_agent_sp", "date", "place"},
            ),
        }

        self.assertEqual(set(DOCUMENT_DATA_FIELDS), set(expected))
        self.assertEqual(len(expected), 10)
        for document_type, (data_field, schema, required_fields) in expected.items():
            self.assertEqual(DOCUMENT_DATA_FIELDS[document_type], data_field)
            self.assertEqual(set(schema.model_fields), required_fields)

    def test_unknown_document_type_is_rejected(self):
        with self.assertRaises(ValueError):
            MasterDocumentIntelligencePayload(
                document_type="UNKNOWN",
                text_medium="PRINTED",
            )

    def test_config_reports_missing_gemini_key(self):
        with patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "",
                "AZURE_OPENAI_API_KEY": "",
                "AZURE_OPENAI_BASE_URL": "",
                "AZURE_OPENAI_MODEL": "",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY or"):
                create_openai_clients()


class OcrImageTests(unittest.TestCase):
    def test_document_ai_processes_page_and_returns_ocr_text_and_confidence(self):
        class FakeClient:
            def processor_path(self, project, location, processor_id):
                return (
                    f"projects/{project}/locations/{location}/"
                    f"processors/{processor_id}"
                )

            def process_document(self, request):
                self.request = request
                return SimpleNamespace(
                    document=SimpleNamespace(
                        text="PAN ABCDE1234F",
                        pages=[
                            SimpleNamespace(
                                tokens=[
                                    SimpleNamespace(
                                        layout=SimpleNamespace(confidence=0.8)
                                    ),
                                    SimpleNamespace(
                                        layout=SimpleNamespace(confidence=1.0)
                                    ),
                                ]
                            )
                        ],
                    )
                )

        cloud = types.ModuleType("google.cloud")
        cloud.documentai = SimpleNamespace(
            RawDocument=lambda **kwargs: SimpleNamespace(**kwargs)
        )
        google = types.ModuleType("google")
        google.__path__ = []
        google.cloud = cloud
        settings = AppConfig(
            ai_primary_provider="gemini",
            gemini_api_key="",
            gemini_model="gemini-test",
            azure_api_key="",
            azure_base_url="",
            azure_model="",
            azure_auth_mode="api-key",
            tavily_api_key="",
            excel_file_path="inventory.xlsx",
            gcp_project_id="project",
            gcp_location="us",
            docai_processor_id="processor",
            google_application_credentials="",
            field_confidence_threshold=0.85,
            handwriting_penalty=0.2,
            log_file="agent.log",
            log_level="INFO",
        )
        client = FakeClient()

        with (
            patch(
                "document_intelligence.utils.google_document_ai.get_config",
                return_value=settings,
            ),
            patch(
                "document_intelligence.utils.google_document_ai.validate_document_ai_config"
            ),
            patch.dict(
                sys.modules,
                {"google": google, "google.cloud": cloud},
            ),
        ):
            result = GoogleDocumentAIProcessor(client=client).process(
                b"image bytes",
                "image/png",
            )

        self.assertEqual(result.text, "PAN ABCDE1234F")
        self.assertEqual(result.confidence, 0.9)
        self.assertEqual(
            client.request["name"],
            "projects/project/locations/us/processors/processor",
        )
        self.assertEqual(client.request["raw_document"].mime_type, "image/png")

    def test_png_mime_type_is_preserved_in_document_ai_request(self):
        document_ai = SimpleNamespace(
            process=lambda content, mime_type: SimpleNamespace(
                text="recognized text",
                confidence=0.93,
            )
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = os.path.join(temporary_directory, "scan.png")
            with open(image_path, "wb") as image_file:
                image_file.write(b"\x89PNG\r\n\x1a\nimage-data")

            with (
                patch.object(Config, "validate"),
                patch(
                    "document_intelligence.utils.ocr.create_openai_clients",
                    return_value=[],
                ),
                patch(
                    "document_intelligence.utils.ocr.GoogleDocumentAIProcessor",
                    return_value=document_ai,
                ),
            ):
                processor = MultimodalOCRProcessor()
                result = processor.execute_raw_ocr_analysis(image_path)

        self.assertEqual(
            result,
            {
                "raw_text": "recognized text",
                "ocr_confidence": 0.93,
                "status": "SUCCESS",
            },
        )

    def test_unsupported_image_type_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = os.path.join(temporary_directory, "scan.bmp")
            with open(image_path, "wb") as image_file:
                image_file.write(b"image-data")

            with (
                patch.object(Config, "validate"),
                patch(
                    "document_intelligence.utils.ocr.create_openai_clients",
                    return_value=[],
                ),
            ):
                processor = MultimodalOCRProcessor()
                with self.assertRaisesRegex(ValueError, "Unsupported image type"):
                    processor.execute_raw_ocr_analysis(image_path)


if __name__ == "__main__":
    unittest.main()
