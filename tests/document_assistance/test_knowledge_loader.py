import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import pymupdf

from document_assistance.core.loader import (
    extract_uploaded_document,
    load_knowledge_base,
    load_docx_sections,
    split_text,
)


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

    def test_uploaded_text_is_extracted_and_empty_text_is_rejected(self):
        sections = extract_uploaded_document("evidence.txt", b"Policy number PL-123")

        self.assertEqual(sections, [("Page 1", "Policy number PL-123")])
        with self.assertRaisesRegex(ValueError, "empty"):
            extract_uploaded_document("empty.txt", b"")

    def test_uploaded_pdf_text_keeps_page_citations(self):
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((50, 50), "Policy number PL-456")
        content = document.tobytes()
        document.close()

        sections = extract_uploaded_document("policy.pdf", content)

        self.assertEqual(sections[0][0], "Page 1")
        self.assertIn("PL-456", sections[0][1])

    def test_uploaded_docx_extracts_text_without_executing_document_content(self):
        content = BytesIO()
        xml = (
            b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/'
            b'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
            b'Policy number PL-123'
            b'</w:t></w:r></w:p></w:body></w:document>'
        )
        with ZipFile(content, "w") as archive:
            archive.writestr("word/document.xml", xml)

        sections = extract_uploaded_document("evidence.docx", content.getvalue())

        self.assertEqual(sections[0][0], "Document body")
        self.assertIn("PL-123", sections[0][1])

    def test_text_is_split_into_overlapping_bounded_chunks(self):
        text = " ".join(f"word{index}" for index in range(500))

        chunks = split_text(text, chunk_size=120, overlap=20)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks))
        self.assertIn(chunks[0].split()[-1], chunks[1].split()[:5])

    def test_application_knowledge_base_loads_multiple_text_sources(self):
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "privacy.txt").write_text(
                "Verification data is private.",
                encoding="utf-8",
            )
            (root / "ignored.md").write_text(
                "This file is not an approved source.",
                encoding="utf-8",
            )
            (root / "nested").mkdir()
            (root / "nested" / "review.txt").write_text(
                "Low-confidence fields need review.",
                encoding="utf-8",
            )

            sections = load_knowledge_base(root)

        self.assertEqual(
            {section.source for section in sections},
            {"privacy.txt", "nested/review.txt"},
        )
        self.assertTrue(any("private" in section.text for section in sections))


if __name__ == "__main__":
    unittest.main()
