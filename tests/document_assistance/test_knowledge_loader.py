import unittest
from pathlib import Path

from document_assistance.core.loader import load_docx_sections


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_DOCUMENT = (
    REPOSITORY_ROOT
    / "document_assistance"
    / "knowledge_base"
    / "Questions.docx"
)


class KnowledgeLoaderTests(unittest.TestCase):
    def test_questions_document_is_loaded_with_citable_sections(self):
        sections = load_docx_sections(QUESTIONS_DOCUMENT)

        citations = {section.section for section in sections}
        content = "\n".join(section.text for section in sections)

        self.assertIn("Excel data agent requirements", citations)
        self.assertIn("Document support assistant requirements", citations)
        self.assertIn("Document intelligence requirements", citations)
        self.assertIn("Required extraction targets", citations)
        self.assertIn("Deliverables", citations)
        self.assertIn("Evaluation criteria", citations)
        self.assertIn("IFSC", content)

    def test_sections_reference_the_source_document(self):
        sections = load_docx_sections(QUESTIONS_DOCUMENT)

        self.assertTrue(sections)
        self.assertTrue(
            all(section.citation.startswith("Questions.docx — ") for section in sections)
        )

    def test_missing_document_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_docx_sections(QUESTIONS_DOCUMENT.with_name("missing.docx"))


if __name__ == "__main__":
    unittest.main()
