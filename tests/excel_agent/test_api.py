import tempfile
import unittest
import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk
from openpyxl import Workbook

from excel_agent import agent, api
from excel_agent.agent import get_llm
from main import app


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
        response = TestClient(app).get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Intelligent Document &amp; Data Processing", response.text)
        self.assertIn('data-route="document-intelligence"', response.text)
        self.assertIn("/api/chat/stream", response.text)
        self.assertIn('payload.event === "status"', response.text)
        self.assertIn("receivedToken = false", response.text)
        self.assertIn('id="excel-file"', response.text)
        self.assertIn('fileInput.addEventListener("change", uploadWorkbook)', response.text)
        self.assertIn("Choose a file to upload it automatically.", response.text)
        self.assertIn("/api/data/upload", response.text)
        self.assertIn("/ui/data-upload.css", response.text)
        self.assertIn("sessionStorage", response.text)

    def test_data_upload_stylesheet_is_served(self):
        response = TestClient(app).get("/ui/data-upload.css")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"].split(";")[0], "text/css")
        self.assertIn(".workbook-upload-panel", response.text)

    def test_stream_endpoint_returns_agent_events(self):
        graph = FakeGraph()
        with patch.object(api.agent, "compiled_graph", graph):
            response = TestClient(app).post(
                "/api/chat/stream",
                json={"message": "How much stock?", "thread_id": "test-session"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["content-type"].split(";")[0],
            "text/event-stream",
        )
        self.assertIn("no-cache", response.headers["cache-control"])
        events = response.text
        self.assertIn('"event": "token"', events)
        self.assertIn('"event": "status"', events)
        self.assertIn('"text": "Thinking..."', events)
        self.assertIn('"text": "Inventory answer"', events)
        self.assertIn('"event": "metrics_evaluation"', events)
        self.assertTrue(events.endswith("data: [DONE]\n\n"))
        self.assertEqual(graph.config["configurable"]["thread_id"], "test-session")
        self.assertEqual(graph.version, "v2")

    def test_reasoning_node_aggregates_explicit_model_stream(self):
        class StreamingRunnable:
            async def astream(self, messages):
                yield AIMessageChunk(content="Live ")
                yield AIMessageChunk(content="answer")

        class FakeLLM:
            def bind_tools(self, tools):
                return StreamingRunnable()

        with patch.object(agent, "get_llm", return_value=FakeLLM()):
            result = asyncio.run(agent.analyst_reasoning_node({"messages": []}))

        self.assertEqual(result["messages"][0].content, "Live answer")

    def test_stream_errors_are_sanitized_and_still_end_with_done_sentinel(self):
        class FailingGraph:
            async def astream_events(self, initial_input, config, version):
                raise RuntimeError("private upstream failure detail")
                yield {}

        with patch.object(api.agent, "compiled_graph", FailingGraph()):
            response = TestClient(app).post(
                "/api/chat/stream",
                json={"message": "How much stock?", "thread_id": "test-session"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn('"event": "error"', response.text)
        self.assertIn("Check the server log", response.text)
        self.assertNotIn("private upstream failure detail", response.text)
        self.assertTrue(response.text.endswith("data: [DONE]\n\n"))

    def test_chat_requires_a_session_id_to_avoid_shared_conversation_state(self):
        response = TestClient(app).post(
            "/api/chat/stream",
            json={"message": "How much stock?"},
        )

        self.assertEqual(response.status_code, 422)

    def test_settings_report_the_effective_azure_only_provider(self):
        with patch.dict(
            "os.environ",
            {
                "AI_PRIMARY_PROVIDER": "gemini",
                "GEMINI_API_KEY": "",
                "AZURE_OPENAI_BASE_URL": "https://proxy.example/v1",
                "AZURE_OPENAI_API_KEY": "azure-test",
                "AZURE_OPENAI_MODEL": "azure-model",
            },
            clear=True,
        ):
            response = TestClient(app).get("/api/documents/settings")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["primary_provider"],
            "Azure OpenAI-compatible provider",
        )
        self.assertEqual(
            response.json()["available_providers"],
            ["Azure OpenAI-compatible provider"],
        )

    def test_excel_upload_loads_workbook_and_returns_schema(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Product", "Stock"])
        sheet.append(["Pen", 12])
        from io import BytesIO

        content = BytesIO()
        workbook.save(content)
        schema = {
            "total_rows": 1,
            "columns": ["Product", "Stock"],
            "data_types": {"Product": "str", "Stock": "int64"},
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(api, "UPLOAD_DIRECTORY", Path(temporary_directory)),
                patch.object(
                    api.agent,
                    "set_dataset",
                    return_value=schema,
                ) as load_dataset,
            ):
                response = TestClient(app).post(
                    "/api/data/upload",
                    files={
                        "file": (
                            "products.xlsx",
                            content.getvalue(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                    },
                )
                uploaded_path = load_dataset.call_args.args[0]
                self.assertTrue(Path(uploaded_path).is_file())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total_rows"], 1)
        self.assertEqual(response.json()["columns"], ["Product", "Stock"])

    def test_excel_upload_replaces_the_active_agent_dataset(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["UploadedProduct", "Units"])
        sheet.append(["CUSTOM_FILE_SENT", 37])
        content = BytesIO()
        workbook.save(content)
        original_dataset = agent.df, agent.schema_context, agent.sandbox_repl

        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                with patch.object(
                    api,
                    "UPLOAD_DIRECTORY",
                    Path(temporary_directory),
                ):
                    response = TestClient(app).post(
                        "/api/data/upload",
                        files={
                            "file": (
                                "custom-workbook.xlsx",
                                content.getvalue(),
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
                        },
                    )
                    schema_response = TestClient(app).get("/api/data/schema")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["columns"], ["UploadedProduct", "Units"])
            self.assertEqual(response.json()["total_rows"], 1)
            self.assertEqual(schema_response.status_code, 200)
            self.assertEqual(
                schema_response.json()["first_3_rows_sample"],
                [{"UploadedProduct": "CUSTOM_FILE_SENT", "Units": 37}],
            )
            self.assertEqual(
                agent.sandbox_repl.execute_code(
                    "print(df['UploadedProduct'].iloc[0])"
                ).strip(),
                "CUSTOM_FILE_SENT",
            )
        finally:
            agent.df, agent.schema_context, agent.sandbox_repl = original_dataset

    def test_excel_upload_rejects_non_excel_file(self):
        response = TestClient(app).post(
            "/api/data/upload",
            files={"file": ("notes.txt", b"not excel", "text/plain")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Excel workbook", response.json()["detail"])

    def test_missing_gemini_key_fails_with_actionable_error(self):
        with patch.dict(
            "os.environ",
            {
                "GEMINI_API_KEY": "",
                "AZURE_OPENAI_API_KEY": "",
                "AZURE_OPENAI_BASE_URL": "",
                "AZURE_OPENAI_MODEL": "",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY or"):
                get_llm()

    def test_excel_agent_uses_configured_gemini_endpoint(self):
        with (
            patch.dict(
                "os.environ",
                {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "test-model"},
                clear=True,
            ),
            patch("datapilot.llm_provider.ChatOpenAI") as chat_model,
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
