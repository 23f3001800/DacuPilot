import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from document_assistance.core import document
from document_assistance.core.loader import load_knowledge_base
from document_assistance.core.retrieval import Evidence, RankedEvidence


KNOWLEDGE_BASE_DIR = Path(__file__).resolve().parents[2] / "document_assistance" / "knowledge_base"


class CompanyHelpKnowledgeBaseTests(unittest.TestCase):
    def test_general_answer_drops_unresolved_citation_ranges(self):
        self.assertEqual(document._validate_citations("General answer [E1–E5]", []), "General answer")

    def test_active_package_contains_company_sources_only(self):
        expected = {"nimbus_orchard_handbook.pdf", "privacy_policy.pdf"}
        sections = load_knowledge_base(KNOWLEDGE_BASE_DIR)

        self.assertEqual({section.source for section in sections}, expected)
        self.assertEqual({section.source for section in document.KNOWLEDGE_SECTIONS}, expected)
        self.assertFalse((KNOWLEDGE_BASE_DIR / "application_knowledge_base.pdf").exists())
        self.assertTrue(
            (KNOWLEDGE_BASE_DIR.parent / "archived_sources" / "application_knowledge_base.pdf").is_file()
        )

    def test_workbook_questions_are_handed_to_data_agent_before_llm_call(self):
        for question in (
            "Add a new column Profit Margin using profit divided by revenue",
            "Create a chart from my data",
            "df['Stock_Variance'] = df['Computed'] - df['Actual']",
        ):
            with self.subTest(question=question), patch.object(document, "get_llm") as get_llm:
                result = document.document_assistant_node(
                    {"messages": [HumanMessage(content=question)], "session_id": "scope-test"}
                )
                get_llm.assert_not_called()
                self.assertEqual(result["last_evaluation"]["scope"], "handoff")
                self.assertIsNone(result["last_evaluation"]["confidence_score"])
                self.assertIn("Data Analysis Agent", result["messages"][0].content)

    def test_policy_question_with_greeting_still_requires_evidence(self):
        question = "Hi, help me understand the company leave policy."
        self.assertFalse(document._is_greeting_or_conversational(question))
        self.assertTrue(document._requires_document_evidence(question))
        with (
            patch.object(document, "retrieve_evidence", return_value=("application", [])),
            patch.object(document, "get_llm") as get_llm,
        ):
            result = document.document_assistant_node(
                {"messages": [HumanMessage(content=question)], "session_id": "company-help-test"}
            )
        get_llm.assert_not_called()
        self.assertIsNone(result["last_evaluation"]["confidence_score"])
        self.assertIn("don't have enough evidence", result["messages"][0].content)

    def test_general_questions_do_not_inherit_application_processing_rules(self):
        self.assertTrue(document._is_greeting_or_conversational("hello, hello"))
        self.assertFalse(document._is_data_analysis_request("What is 2 + 2?"))
        self.assertFalse(document._requires_document_evidence("What is the capital of Japan?"))
        self.assertFalse(document._requires_document_evidence("What happens when confidence is low?"))
        self.assertTrue(document._requires_document_evidence("What is the company leave policy?"))

    def test_general_answer_ignores_accidental_handbook_matches(self):
        class MockGeneralLLM:
            messages = None

            def invoke(self, messages):
                self.messages = messages
                return AIMessage(content="Tokyo is the capital of Japan.")

        model = MockGeneralLLM()
        with patch.object(document, "get_llm", return_value=model):
            result = document.document_assistant_node(
                {"messages": [HumanMessage(content="What is the capital of Japan?")], "session_id": "general-test"}
            )

        self.assertEqual(result["last_scope"], "general")
        self.assertIsNone(result["last_evaluation"]["confidence_score"])
        self.assertNotIn("nimbus_orchard_handbook.pdf", model.messages[1].content)
        self.assertIn("Tokyo is the capital", result["messages"][-1].content)
        self.assertNotIn("Source:", result["messages"][-1].content)

    def test_company_answer_uses_company_citations(self):
        evidence = RankedEvidence(
            evidence=Evidence(
                source_id="company-leave",
                source="nimbus_orchard_handbook.pdf",
                source_type="application_kb",
                authority="authoritative_application_knowledge",
                section="Leave and holidays",
                text="Employees submit leave requests through the company process.",
                chunk_id="company-leave",
            ),
            score=0.8,
        )

        class MockCompanyLLM:
            def invoke(self, messages):
                return AIMessage(content="Submit a leave request through the company process. [E1]")

        with (
            patch.object(document, "retrieve_evidence", return_value=("application", [evidence])),
            patch.object(document, "get_llm", return_value=MockCompanyLLM()),
        ):
            result = document.document_assistant_node(
                {"messages": [HumanMessage(content="What is the company leave policy?")], "session_id": "company-test"}
            )

        self.assertEqual(result["last_scope"], "application")
        self.assertEqual(result["last_evaluation"]["sources"], ["nimbus_orchard_handbook.pdf"])
        self.assertIn(
            "Source: [nimbus_orchard_handbook.pdf — Leave and holidays]",
            result["messages"][-1].content,
        )


    def test_filename_question_keeps_uploaded_document_evidence(self):
        evidence = RankedEvidence(
            evidence=Evidence(
                source_id="user-benefits",
                source="benefits.txt",
                source_type="user_document",
                authority="user_provided_evidence",
                section="Page 1",
                text="The support email in this file is help@example.test.",
                session_id="upload-test",
                chunk_id="user-benefits",
            ),
            score=0.8,
        )

        class MockDocumentLLM:
            def invoke(self, messages):
                return AIMessage(content="The file lists help@example.test. [E1]")

        with (
            patch.object(document, "retrieve_evidence", return_value=("user", [evidence])),
            patch.object(document, "get_llm", return_value=MockDocumentLLM()),
        ):
            result = document.document_assistant_node(
                {"messages": [HumanMessage(content="Summarize benefits.txt")], "session_id": "upload-test"}
            )

        self.assertEqual(result["last_scope"], "user")
        self.assertEqual(result["last_evaluation"]["sources"], ["benefits.txt"])
        self.assertIn("Source: [benefits.txt — Page 1]", result["messages"][-1].content)

if __name__ == "__main__":
    unittest.main()
