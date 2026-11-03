import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage

from document_assistance.core import document
from document_assistance.core.loader import load_knowledge_base
from document_assistance.core.retrieval import (
    CHROMA_STORE,
    SessionDocumentStore,
    retrieve_evidence,
    route_query,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = (
    REPOSITORY_ROOT
    / "document_assistance"
    / "knowledge_base"
)


class ApplicationKnowledgeBaseTests(unittest.TestCase):
    def test_application_knowledge_base_pdf_exists_and_loads_all_six_policies(self):
        """Verify application_knowledge_base.pdf is ingested with all 6 required policy sections."""
        pdf_path = KNOWLEDGE_BASE_DIR / "application_knowledge_base.pdf"
        self.assertTrue(pdf_path.is_file(), "application_knowledge_base.pdf must exist in knowledge_base/")

        sections = load_knowledge_base(KNOWLEDGE_BASE_DIR)
        app_sections = [s for s in sections if "application_knowledge_base.pdf" in s.source]
        self.assertGreaterEqual(len(app_sections), 6, "At least 6 sections must be extracted from the PDF")

        section_titles = [s.section for s in app_sections]
        required_policies = [
            "Privacy Policy",
            "Verification Policy",
            "Document Definitions",
            "Confidence Policy",
            "Human Review Policy",
            "Application Guidelines",
        ]
        for policy in required_policies:
            self.assertTrue(
                any(policy in title for title in section_titles),
                f"Missing required policy in PDF: {policy}",
            )

    def test_runtime_knowledge_uses_one_privacy_source_and_keeps_document_guidance(self):
        sections = document.KNOWLEDGE_SECTIONS
        self.assertFalse(
            any(
                Path(section.source).name == "application_knowledge_base.pdf"
                and section.section.casefold().startswith("privacy policy")
                for section in sections
            )
        )
        self.assertTrue(any(Path(section.source).name == "privacy_policy.pdf" for section in sections))
        self.assertTrue(
            any(
                Path(section.source).name == "application_knowledge_base.pdf"
                and "confidence" in section.section.casefold()
                for section in sections
            )
        )

    def test_workbook_questions_are_handed_to_data_agent_before_llm_call(self):
        for question in (
            "Add a new column Profit Margin using profit divided by revenue",
            "Create a chart from my data",
            "df['Stock_Variance'] = df['Computed'] - df['Actual']",
        ):
            with self.subTest(question=question):
                result = document.document_assistant_node(
                    {
                        "messages": [HumanMessage(content=question)],
                        "session_id": "document-scope-test",
                    }
                )
                self.assertEqual(result["last_evaluation"]["scope"], "handoff")
                self.assertIsNone(result["last_evaluation"]["confidence_score"])
                self.assertIn("Data Analysis Agent", result["messages"][0].content)

    def test_general_and_company_help_questions_are_not_misrouted(self):
        self.assertFalse(document._is_data_analysis_request("What is 2 + 2?"))
        self.assertFalse(document._is_data_analysis_request("What is the company leave policy?"))
        self.assertFalse(document._requires_document_evidence("What is the capital of Japan?"))
        self.assertTrue(document._requires_document_evidence("What happens when confidence is low?"))

    def test_general_answer_ignores_accidental_handbook_matches(self):
        class MockGeneralLLM:
            messages = None

            def invoke(self, messages):
                self.messages = messages
                return AIMessage(content="Tokyo is the capital of Japan.")

        model = MockGeneralLLM()
        with patch.object(document, "get_llm", return_value=model):
            result = document.document_assistant_node(
                {
                    "messages": [HumanMessage(content="What is the capital of Japan?")],
                    "session_id": "general-question-test",
                }
            )

        self.assertEqual(result["last_scope"], "general")
        self.assertEqual(result["current_topic"], "General assistance")
        self.assertEqual(result["last_evaluation"]["scope"], "general")
        self.assertIsNone(result["last_evaluation"]["confidence_score"])
        self.assertNotIn("nimbus_orchard_handbook.pdf", model.messages[1].content)
        self.assertIn("Tokyo is the capital", result["messages"][-1].content)

    def test_chroma_semantic_retrieval_and_metadata_for_low_confidence_query(self):
        """Verify query 'What happens when confidence is low?' retrieves confidence/review policies via ChromaDB."""
        sections = load_knowledge_base(KNOWLEDGE_BASE_DIR)
        store = SessionDocumentStore()
        session_id = f"test-conf-{uuid4().hex[:8]}"

        query = "What happens when confidence is low?"
        scope = route_query(query, user_store=store, session_id=session_id)
        self.assertEqual(scope, "application")

        scope, evidence_pack = retrieve_evidence(
            query,
            sections,
            session_id,
            store,
            limit=5,
        )

        self.assertEqual(scope, "application")
        self.assertTrue(evidence_pack, "Evidence pack should contain retrieved chunks")

        # Top hit must be from application_knowledge_base.pdf with Human Review or Confidence policy
        top_hit = evidence_pack[0]
        self.assertIn("application_knowledge_base.pdf", top_hit.evidence.source)
        self.assertTrue(
            any(kw in top_hit.evidence.section for kw in ("Human Review", "Confidence")),
            f"Expected Human Review or Confidence section in top hit, got: {top_hit.evidence.section}",
        )
        self.assertTrue(
            any("HUMAN_REVIEWS_REQUIRED" in hit.evidence.text or "Human Review" in hit.evidence.section or "Confidence Policy" in hit.evidence.section for hit in evidence_pack),
            "Expected Human Review or Confidence policy in retrieved evidence pack",
        )

        # Verify metadata extraction (Document + Section + Page + Chunk ID)
        self.assertTrue(top_hit.evidence.source.endswith(".pdf"))
        self.assertTrue(bool(top_hit.evidence.section))
        self.assertTrue(bool(top_hit.evidence.chunk_id or top_hit.evidence.source_id))

    def test_document_assistant_end_to_end_grounded_answer_with_citations(self):
        """Verify full agent invocation produces grounded response with section/page citation."""
        class MockGroundedLLM:
            def invoke(self, messages):
                return AIMessage(
                    content=(
                        "When confidence is low (below 0.85 threshold), automated processing is suspended, "
                        "the document status is set to HUMAN_REVIEWS_REQUIRED, and flagged fields are routed "
                        "to human operators for manual verification. [E1]"
                    )
                )

        thread_id = f"conf-test-{uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        with patch.object(document, "get_llm", return_value=MockGroundedLLM()):
            result = document.compiled_agent.invoke(
                {"messages": [HumanMessage(content="What happens when confidence is low?")], "session_id": thread_id},
                config=config,
            )

            answer = result["messages"][-1].content
            self.assertIn("HUMAN_REVIEWS_REQUIRED", answer)
            self.assertIn("Source: [application_knowledge_base.pdf — ", answer)
            self.assertEqual(result.get("last_scope"), "application")
            self.assertGreaterEqual(result.get("last_evaluation", {}).get("confidence_score", 0), 0.70)


if __name__ == "__main__":
    unittest.main()
