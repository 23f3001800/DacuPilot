import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from excel_agent import api
from excel_agent.agent import get_llm


class FakeGraph:
    async def astream_events(self, initial_input, config, version):
        self.initial_input = initial_input
        self.config = config
        self.version = version
        yield {
            "event": "on_chat_model_stream",
            "name": "ChatOpenAI",
            "data": {
                "chunk": SimpleNamespace(content="Inventory answer", additional_kwargs={})
            },
        }
        yield {
            "event": "on_chain_end",
            "name": "run_evaluation",
            "data": {
                "output": {
                    "structured_response": {
                        "conversational_summary": "Inventory answer",
                        "evaluation_metrics": {"confidence_score": 0.95},
                    }
                }
            },
        }


class ExcelApiTests(unittest.TestCase):
    def test_homepage_serves_inventory_chat_ui(self):
        response = TestClient(api.app).get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Ask questions about your inventory", response.text)
        self.assertIn("/api/chat/stream", response.text)
        self.assertIn("sessionStorage", response.text)

    def test_stream_endpoint_returns_agent_events(self):
        graph = FakeGraph()
        with patch.object(api, "compiled_graph", graph):
            response = TestClient(api.app).post(
                "/api/chat/stream",
                json={"message": "How much stock?", "thread_id": "test-session"},
            )

        self.assertEqual(response.status_code, 200)
        events = response.text
        self.assertIn('"event": "token"', events)
        self.assertIn('"text": "Inventory answer"', events)
        self.assertIn('"event": "metrics_evaluation"', events)
        self.assertTrue(events.endswith("data: [DONE]\n\n"))
        self.assertEqual(graph.config["configurable"]["thread_id"], "test-session")
        self.assertEqual(graph.version, "v2")

    def test_chat_requires_a_session_id_to_avoid_shared_conversation_state(self):
        response = TestClient(api.app).post(
            "/api/chat/stream",
            json={"message": "How much stock?"},
        )

        self.assertEqual(response.status_code, 422)

    def test_missing_gemini_key_fails_with_actionable_error(self):
        with patch.dict("os.environ", {"GEMINI_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
                get_llm()

    def test_excel_agent_uses_configured_gemini_endpoint(self):
        with (
            patch.dict(
                "os.environ",
                {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "test-model"},
            ),
            patch("excel_agent.agent.ChatOpenAI") as chat_model,
        ):
            get_llm()

        chat_model.assert_called_once_with(
            model="test-model",
            api_key="test-key",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            temperature=0.1,
            streaming=True,
        )


if __name__ == "__main__":
    unittest.main()
