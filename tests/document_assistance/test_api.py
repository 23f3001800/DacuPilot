import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from document_assistance.api import router
from document_assistance.core.retrieval import SessionDocumentStore
from fastapi import FastAPI
from main import app as root_app


class DocumentAssistantApiTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)
        self.session_id = str(uuid4())

    def test_document_upload_indexes_utf8_text_for_its_session(self):
        store = SessionDocumentStore()
        with patch("document_assistance.api.USER_DOCUMENTS", store):
            response = self.client.post(
                "/api/document-assistant/documents",
                data={
                    "thread_id": self.session_id,
                    "external_processing_consent": "true",
                },
                files={
                    "files": (
                        "policy.txt",
                        b"Policy number PL-12345",
                        "text/plain",
                    )
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["thread_id"], self.session_id)
        self.assertEqual(response.json()["documents"][0]["filename"], "policy.txt")
        self.assertEqual(
            store.get_session_evidence(self.session_id)[0].source_type,
            "user_document",
        )

    def test_document_upload_rejects_invalid_session_identifiers(self):
        response = self.client.post(
            "/api/document-assistant/documents",
            data={
                "thread_id": "not-a-uuid",
                "external_processing_consent": "true",
            },
            files={"files": ("policy.txt", b"policy", "text/plain")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("valid session UUID", response.json()["detail"])

    def test_root_app_mounts_document_assistant_upload_and_chat_routes(self):
        paths = set(root_app.openapi()["paths"])

        self.assertIn("/api/document-assistant/chat", paths)
        self.assertIn("/api/document-assistant/chat/stream", paths)
        self.assertIn("/api/document-assistant/documents", paths)
        self.assertIn("/api/document-assistant/session/{thread_id}", paths)

    def test_homepage_matches_document_assistant_knowledge_without_external_upload(self):
        response = TestClient(root_app).get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Nimbus Orchard Technologies Company Handbook", response.text)
        self.assertIn("What is the annual leave entitlement?", response.text)
        self.assertNotIn('id="document-assistant-files"', response.text)
        self.assertNotIn('id="document-assistant-consent"', response.text)
        self.assertNotIn('id="document-assistant-attach"', response.text)
        self.assertNotIn('id="document-assistant-upload-form"', response.text)
        self.assertNotIn("Questions.docx", response.text)
        self.assertNotIn("assignment knowledge document", response.text)

    def test_chat_endpoint_passes_the_session_id_to_conversation_state(self):
        messages = [
            HumanMessage(content="What is the confidence threshold?"),
            AIMessage(content="Review low-confidence fields."),
        ]
        with patch(
            "document_assistance.api.compiled_agent.invoke",
            return_value={"messages": messages, "current_topic": "Document support"},
        ) as invoke:
            response = self.client.post(
                "/api/document-assistant/chat",
                json={
                    "message": "What is the confidence threshold?",
                    "thread_id": self.session_id,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(invoke.call_args.args[0]["session_id"], self.session_id)
        self.assertEqual(response.json()["answer"], "Review low-confidence fields.")

    def test_stream_endpoint_returns_sse_events(self):
        async def mock_astream(messages):
            yield AIMessage(content="Annual leave is 25 days [E1].")

        mock_llm = MagicMock()
        mock_llm.astream = mock_astream

        with patch("document_assistance.api.get_llm", return_value=mock_llm):
            response = self.client.post(
                "/api/document-assistant/chat/stream",
                json={
                    "message": "What is the annual leave policy?",
                    "thread_id": self.session_id,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertIn("data: [DONE]", response.text)
        self.assertIn('"event": "status"', response.text)
        self.assertIn('"event": "token"', response.text)

    def test_multi_file_upload_is_atomic_when_a_document_is_invalid(self):
        store = SessionDocumentStore()
        with patch("document_assistance.api.USER_DOCUMENTS", store):
            response = self.client.post(
                "/api/document-assistant/documents",
                data={
                    "thread_id": self.session_id,
                    "external_processing_consent": "true",
                },
                files=[
                    ("files", ("valid.txt", b"valid policy content", "text/plain")),
                    ("files", ("broken.docx", b"not a docx", "application/zip")),
                ],
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(store.get_session_evidence(self.session_id), [])

    def test_document_upload_requires_external_processing_consent(self):
        response = self.client.post(
            "/api/document-assistant/documents",
            data={"thread_id": self.session_id},
            files={"files": ("policy.txt", b"policy content", "text/plain")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Consent is required", response.json()["detail"])

    def test_delete_endpoint_clears_private_document_evidence(self):
        store = SessionDocumentStore()
        store.add_document(
            self.session_id,
            "policy.txt",
            [("Page 1", "Policy number PL-1")],
        )
        with patch("document_assistance.api.USER_DOCUMENTS", store):
            response = self.client.delete(
                f"/api/document-assistant/session/{self.session_id}"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["removed_chunks"], 1)
        self.assertEqual(store.get_session_evidence(self.session_id), [])
        self.assertTrue(response.json()["conversation_cleared"])


if __name__ == "__main__":
    unittest.main()
