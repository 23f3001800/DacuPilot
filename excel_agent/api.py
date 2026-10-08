import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from .agent import compiled_graph, logger

app = FastAPI(title="Enterprise Data Agent SSE API")
UI_FILE = Path(__file__).resolve().parent.parent / "ui" / "index.html"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)


@app.get("/", include_in_schema=False)
async def chat_ui():
    return FileResponse(UI_FILE)


async def sse_event_generator(user_message: str, thread_id: str):
    """Stream agent events as server-sent events."""
    config = {"configurable": {"thread_id": thread_id}}
    initial_input = {"messages": [HumanMessage(content=user_message)]}

    logger.info("Initiating stream request for thread session: %s", thread_id)

    try:
        async for event in compiled_graph.astream_events(
            initial_input, config, version="v2"
        ):
            kind = event.get("event")
            name = event.get("name")

            if (
                kind == "on_chat_model_stream"
                and "tool_calls" in event["data"]["chunk"].additional_kwargs
            ):
                tool_chunk = event["data"]["chunk"].additional_kwargs["tool_calls"]
                for tool in tool_chunk:
                    if tool.get("name"):
                        payload = {"event": "tool_start", "tool": tool["name"]}
                        yield f"data: {json.dumps(payload)}\n\n"
            elif kind == "on_chat_model_stream" and name == "ChatOpenAI":
                content = event["data"]["chunk"].content
                if content:
                    payload = {"event": "token", "text": content}
                    yield f"data: {json.dumps(payload)}\n\n"
            elif kind == "on_chain_end" and name == "run_evaluation":
                output_data = event["data"].get("output", {})
                if "structured_response" in output_data:
                    payload = {
                        "event": "metrics_evaluation",
                        "payload": output_data["structured_response"],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
    except Exception as stream_err:
        logger.exception("Streaming anomaly detected")
        payload = {"event": "error", "details": str(stream_err)}
        yield f"data: {json.dumps(payload)}\n\n"
    finally:
        logger.info("Stream generation closed for session thread: %s", thread_id)
        yield "data: [DONE]\n\n"


@app.post("/api/chat/stream")
async def stream_chat_endpoint(payload: ChatRequest):
    """Expose the agent's event stream over HTTP."""
    return StreamingResponse(
        sse_event_generator(payload.message, payload.thread_id),
        media_type="text/event-stream",
    )
