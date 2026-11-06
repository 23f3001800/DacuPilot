import tempfile
import unittest
import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from openpyxl import Workbook

from excel_agent import agent, api
from excel_agent.agent import DatasetContext
from excel_agent.agent import get_llm
from excel_agent.engine import PythonSandboxREPL
from main import app

TEST_THREAD_ID = "00000000-0000-4000-8000-000000000001"


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
    def setUp(self):
        self._orig_context = agent._datasets.get(TEST_THREAD_ID)
        import pandas as pd
        self.dummy_df = pd.DataFrame({"item": ["pen"], "quantity": [10]})
        self.dummy_schema = {
            "filename": "sample.xlsx",
            "total_rows": 1,
            "columns": ["item", "quantity"],
            "data_types": {"item": "str", "quantity": "int64"},
            "summary": {},
        }
        agent._datasets[TEST_THREAD_ID] = DatasetContext(
            self.dummy_df, self.dummy_schema, PythonSandboxREPL(self.dummy_df)
        )

    def tearDown(self):
        agent._datasets.pop(TEST_THREAD_ID, None)
        if self._orig_context is not None:
            agent._datasets[TEST_THREAD_ID] = self._orig_context

    def test_stream_triggers_guardrail_when_no_workbook_is_loaded(self):
        agent._datasets.pop(TEST_THREAD_ID, None)
        response = TestClient(app).post(
            "/api/chat/stream",
            json={"message": "How much stock?", "thread_id": TEST_THREAD_ID, "processing_consent": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Workbook Required", response.text)
        self.assertIn("No Excel workbook has been uploaded yet", response.text)
        self.assertTrue(response.text.endswith("data: [DONE]\n\n"))

    def test_dataset_contexts_are_isolated_by_workspace_id(self):
        import pandas as pd
        other_id = "00000000-0000-4000-8000-000000000002"
        other_frame = pd.DataFrame({"secret": ["other workspace"]})
        agent._datasets[other_id] = DatasetContext(
            other_frame, {"columns": ["secret"]}, PythonSandboxREPL(other_frame)
        )
        try:
            self.assertEqual(agent.get_dataset_context(TEST_THREAD_ID).schema["filename"], "sample.xlsx")
            self.assertEqual(agent.get_dataset_context(other_id).data_frame.iloc[0, 0], "other workspace")
        finally:
            agent._datasets.pop(other_id, None)

    def test_upload_rejects_the_shared_default_session(self):
        response = TestClient(app).post(
            "/api/data/upload",
            data={"thread_id": "default"},
            files={"file": ("sample.xlsx", b"not a workbook", "application/octet-stream")},
        )

        self.assertEqual(response.status_code, 422)

    def test_schema_endpoint_converts_nested_non_finite_values_to_json_null(self):
        self.dummy_schema["summary"] = {
            "average": float("nan"),
            "maximum": float("inf"),
            "nested": [float("-inf")],
        }

        response = TestClient(app).get(
            "/api/data/schema", params={"thread_id": TEST_THREAD_ID}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["summary"],
            {"average": None, "maximum": None, "nested": [None]},
        )

    def test_homepage_serves_the_vue_workspace_build(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            index = Path(temporary_directory) / "index.html"
            index.write_text(
                '<!doctype html><title>InsightPilot</title><div id="app"></div>'
                '<script type="module" src="/assets/workspace.js"></script>',
                encoding="utf-8",
            )
            with patch("main.FRONTEND_INDEX", index):
                response = TestClient(app).get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn('id="app"', response.text)
        self.assertIn("/assets/workspace.js", response.text)

    def test_missing_frontend_build_returns_an_actionable_error(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with patch("main.FRONTEND_INDEX", Path(temporary_directory) / "missing.html"):
                response = TestClient(app).get("/")

        self.assertEqual(response.status_code, 503)
        self.assertIn("workspace build is unavailable", response.text)
        self.assertIn("npm run build", response.text)

    def test_legacy_frontend_stylesheet_is_not_served(self):
        self.assertEqual(TestClient(app).get("/ui/data-upload.css").status_code, 404)

    def test_app_exposes_analysis_and_extraction_without_company_help(self):
        paths = app.openapi()["paths"]
        self.assertIn("/api/chat/stream", paths)
        self.assertIn("/api/documents/process/stream", paths)
        self.assertFalse(any(path.startswith("/api/document-assistant") for path in paths))
        self.assertEqual(TestClient(app).post("/api/document-assistant/chat", json={}).status_code, 404)

    def test_stream_endpoint_returns_agent_events(self):
        graph = FakeGraph()
        with patch.object(api.agent, "compiled_graph", graph):
            response = TestClient(app).post(
                "/api/chat/stream",
                json={"message": "How much stock?", "thread_id": TEST_THREAD_ID, "processing_consent": True},
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
        self.assertEqual(graph.config["configurable"]["thread_id"], TEST_THREAD_ID)
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
            result = asyncio.run(agent.analyst_reasoning_node({"messages": [], "thread_id": TEST_THREAD_ID}))

        self.assertEqual(result["messages"][0].content, "Live answer")

    def test_stream_exposes_tool_outcome_without_raw_failure_details(self):
        class ToolGraph:
            async def astream_events(self, initial_input, config, version):
                yield {
                    "event": "on_chain_end",
                    "name": "execute_tools",
                    "data": {"output": {"messages": [
                        ToolMessage(content="ERROR: private calculation detail", name="execute_pandas_code", tool_call_id="failed"),
                        ToolMessage(content="10", name="execute_pandas_code", tool_call_id="passed"),
                    ]}},
                }

        with patch.object(api.agent, "compiled_graph", ToolGraph()):
            response = TestClient(app).post(
                "/api/chat/stream",
                json={"message": "Summarize stock", "thread_id": TEST_THREAD_ID, "processing_consent": True},
            )
        self.assertIn('"event": "tool_result", "tool": "execute_pandas_code", "success": false', response.text)
        self.assertIn('"event": "tool_result", "tool": "execute_pandas_code", "success": true', response.text)
        self.assertNotIn("private calculation detail", response.text)

    def test_stream_errors_are_sanitized_and_still_end_with_done_sentinel(self):
        class FailingGraph:
            async def astream_events(self, initial_input, config, version):
                raise RuntimeError("private upstream failure detail")
                yield {}

        with patch.object(api.agent, "compiled_graph", FailingGraph()):
            response = TestClient(app).post(
                "/api/chat/stream",
                    json={"message": "How much stock?", "thread_id": TEST_THREAD_ID, "processing_consent": True},
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
                    data={"thread_id": TEST_THREAD_ID},
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
        original_context = agent._datasets.get(TEST_THREAD_ID)

        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                with patch.object(
                    api,
                    "UPLOAD_DIRECTORY",
                    Path(temporary_directory),
                ):
                    response = TestClient(app).post(
                        "/api/data/upload",
                        data={"thread_id": TEST_THREAD_ID},
                        files={
                            "file": (
                                "custom-workbook.xlsx",
                                content.getvalue(),
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
                        },
                    )
                    schema_response = TestClient(app).get(f"/api/data/schema?thread_id={TEST_THREAD_ID}")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["columns"], ["UploadedProduct", "Units"])
            self.assertEqual(response.json()["total_rows"], 1)
            self.assertEqual(schema_response.status_code, 200)
            self.assertEqual(
                schema_response.json()["first_3_rows_sample"],
                [{"UploadedProduct": "CUSTOM_FILE_SENT", "Units": 37}],
            )
            self.assertEqual(
                agent.get_dataset_context(TEST_THREAD_ID).sandbox.execute_code(
                    "print(df['UploadedProduct'].iloc[0])"
                ).strip(),
                "CUSTOM_FILE_SENT",
            )
        finally:
            agent._datasets.pop(TEST_THREAD_ID, None)
            if original_context is not None:
                agent._datasets[TEST_THREAD_ID] = original_context

    def test_excel_upload_rejects_non_excel_file(self):
        response = TestClient(app).post(
            "/api/data/upload",
            data={"thread_id": TEST_THREAD_ID},
            files={"file": ("notes.txt", b"not excel", "text/plain")},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Excel workbook", response.json()["detail"])

    def test_failed_tool_call_is_not_retried_or_scored_as_success(self):
        tool_message = ToolMessage(
            content="ERROR: Execution timed out after 10 seconds.",
            tool_call_id="call-timeout",
            name="execute_pandas_code",
        )
        self.assertTrue(agent._tool_execution_failed(tool_message.content))
        self.assertEqual(
            agent.route_after_tool_execution(
                {"messages": [HumanMessage(content="Add a computed column"), tool_message]}
            ),
            "run_evaluation",
        )

        result = asyncio.run(
            agent.data_evaluation_node(
                {
                    "messages": [
                        HumanMessage(content="Add a computed column"),
                        tool_message,
                    ],
                    "thread_id": TEST_THREAD_ID,
                }
            )
        )
        payload = result["structured_response"]
        self.assertIn("timed out", payload["assistant_message"].casefold())
        self.assertIn("workbook is unchanged", payload["assistant_message"].casefold())
        self.assertIsNone(payload["evaluation_metrics"]["confidence_score"])

    def test_successful_workbook_evidence_gets_a_nonzero_heuristic_score(self):
        tool_message = ToolMessage(
            content="7",
            tool_call_id="call-result",
            name="execute_pandas_code",
            additional_kwargs={
                "rows_available": 2,
                "columns_referenced": 1,
                "columns_available": 2,
                "referenced_columns": ["quantity"],
                "result_validated": False,
                "non_empty_result": True,
            },
        )
        result = asyncio.run(
            agent.data_evaluation_node(
                {
                    "messages": [
                        HumanMessage(content="What is the quantity total?"),
                        tool_message,
                        AIMessage(content="The total is 7."),
                    ],
                    "thread_id": TEST_THREAD_ID,
                    "tool_rounds": 1,
                }
            )
        )

        metrics = result["structured_response"]["evaluation_metrics"]
        self.assertGreater(metrics["confidence_score"], 0)
        self.assertLessEqual(metrics["confidence_score"], 0.85)
        self.assertGreater(metrics["data_coverage_percentage"], 0)
        self.assertEqual(metrics["data_coverage_percentage"], 80.0)
        self.assertIn("not a calibrated probability", metrics["evaluation_rationale"])

    def test_empty_tool_output_is_not_given_a_confidence_score(self):
        tool_message = ToolMessage(
            content="Code executed successfully with no print output.",
            tool_call_id="call-empty",
            name="execute_pandas_code",
            additional_kwargs={
                "rows_available": 2,
                "columns_referenced": 1,
                "columns_available": 2,
                "non_empty_result": False,
            },
        )
        result = asyncio.run(
            agent.data_evaluation_node(
                {
                    "messages": [HumanMessage(content="Summarize this workbook"), tool_message],
                    "thread_id": TEST_THREAD_ID,
                    "tool_rounds": 1,
                }
            )
        )

        payload = result["structured_response"]
        self.assertIsNone(payload["evaluation_metrics"]["confidence_score"])
        self.assertIn("no printable result", payload["assistant_message"])

    def test_multiline_column_formula_is_parsed_for_preview(self):
        message = (
            "Add column Stock Variance using df['Computed_Closing_Stock'] - "
            "df['Hand-In-\nStock']"
        )
        intent = api._column_intent(message)
        self.assertIsNotNone(intent)
        self.assertEqual(intent[0], "add")
        self.assertEqual(intent[1], "Stock Variance")
        self.assertIn("Hand-In-\nStock", intent[2])

    def test_existing_column_update_and_delete_intents_are_parsed(self):
        update = api._column_intent("Update existing column Profit using df['Revenue'] - df['Cost']")
        delete = api._column_intent("Delete column Legacy Margin")

        self.assertEqual(update, ("update", "Profit", "df['Revenue'] - df['Cost']"))
        self.assertEqual(delete, ("delete", "Legacy Margin", None))

    def test_unparsed_dataframe_assignment_is_stopped_without_local_code(self):
        message = "df['Stock_Variance'] = df['Computed'] - df['Actual']"

        async def collect_events():
            return "".join(
                [event async for event in api.sse_event_generator(message, TEST_THREAD_ID)]
            )

        response = asyncio.run(collect_events())
        self.assertIn("the workbook is unchanged", response)
        self.assertIn("preview", response)
        self.assertIn("local Python", response)
        self.assertTrue(response.endswith("data: [DONE]\n\n"))

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
            timeout=90,
            max_retries=1,
        )


if __name__ == "__main__":
    unittest.main()
