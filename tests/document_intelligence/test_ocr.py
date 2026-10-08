import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from document_intelligence.config import Config
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
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                Config.validate()


class OcrImageTests(unittest.TestCase):
    def test_png_mime_type_is_preserved_in_gemini_image_payload(self):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="recognized text"))]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: response)
            )
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = os.path.join(temporary_directory, "scan.png")
            with open(image_path, "wb") as image_file:
                image_file.write(b"\x89PNG\r\n\x1a\nimage-data")

            with (
                patch.object(Config, "validate"),
                patch("document_intelligence.utils.ocr.OpenAI", return_value=client),
            ):
                processor = MultimodalOCRProcessor()
                result = processor.execute_raw_ocr_analysis(image_path)

        self.assertEqual(result, {"raw_text": "recognized text", "status": "SUCCESS"})

    def test_unsupported_image_type_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = os.path.join(temporary_directory, "scan.bmp")
            with open(image_path, "wb") as image_file:
                image_file.write(b"image-data")

            with (
                patch.object(Config, "validate"),
                patch("document_intelligence.utils.ocr.OpenAI"),
            ):
                processor = MultimodalOCRProcessor()
                with self.assertRaisesRegex(ValueError, "Unsupported image type"):
                    processor.execute_raw_ocr_analysis(image_path)


if __name__ == "__main__":
    unittest.main()
