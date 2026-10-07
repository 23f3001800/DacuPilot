import os
import json
import logging
import asyncio
from typing import TypedDict, Annotated, Sequence, Literal
from pydantic import BaseModel, Field
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from loader import load_real_world_excel
from engine import PythonSandboxREPL
from tavily import TavilyClient

load_dotenv()

# ==========================================
# 1. PRODUCTION ROTATING LOGGING SETUP
# ==========================================
logger = logging.getLogger("DataAgentAPI")
logger.setLevel(logging.INFO)

if not logger.handlers:
    console_formatter = logging.Formatter('⏳ [%(asctime)s] %(levelname)s - %(message)s', '%Y-%m-%d %H:%M:%S')
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    file_formatter = logging.Formatter('[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] - %(message)s')
    file_handler = RotatingFileHandler("agent_server.log", maxBytes=5*1024*1024, backupCount=3)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# ==========================================
# 2. CORE AGENT & DATA CONFIGURATION
# ==========================================
EXCEL_FILE_PATH = "your_complex_file.xlsx"
df, schema_context = load_real_world_excel(EXCEL_FILE_PATH)
sandbox_repl = PythonSandboxREPL(df)
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# Use an async variant of the LLM for streaming capabilities
llm = ChatOpenAI(model="gpt-4o", temperature=0.1, streaming=True)

# Pydantic Schemas
class CodeExecutionInput(BaseModel):
    code: str = Field(description="The executable Pandas code string. You MUST print variables.")

class WebSearchInput(BaseModel):
    query: str = Field(description="The search query for Tavily.")

class AgentMetrics(BaseModel):
    confidence_score: float
    data_coverage_percentage: float
    evaluation_rationale: str

class FinalStructuredPayload(BaseModel):
    conversational_summary: str
    evaluation_metrics: AgentMetrics

class AgentGraphState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    structured_response: FinalStructuredPayload

# ==========================================
# 3. NODE DEFINITIONS
# ==========================================
async def analyst_reasoning_node(state: AgentGraphState):
    system_prompt = SystemMessage(content=f"""
You are an enterprise data analyst agent. You manipulate a preloaded Pandas DataFrame named `df`.
Columns: {schema_context['columns']}
Data Types: {json.dumps(schema_context['data_types'])}
Metrics Count: {schema_context['total_rows']}
""")
    llm_with_tools = llm.bind_tools([
        {"name": "execute_pandas_code", "description": "Run Python code against df REPL.", "parameters": CodeExecutionInput.model_json_schema()},
        {"name": "web_search_lookup", "description": "Search Tavily for definitions.", "parameters": WebSearchInput.model_json_schema()}
    ])
    response = await llm_with_tools.ainvoke([system_prompt] + list(state["messages"]))
    return {"messages": [response]}

async def tool_execution_node(state: AgentGraphState):
    last_msg = state["messages"][-1]
    tool_responses = []
    
    for tool_call in last_msg.tool_calls:
        tool_name = tool_call["name"]
        raw_args = tool_call["args"]
        logger.info(f"Executing tool: '{tool_name}' with arguments: {json.dumps(raw_args)}")
        
        try:
            if tool_name == "execute_pandas_code":
                output = sandbox_repl.execute_code(CodeExecutionInput(**raw_args).code)
            elif tool_name == "web_search_lookup":
                search_res = tavily_client.search(query=WebSearchInput(**raw_args).query, max_results=2).get("results", [])
                output = "\n".join([r['content'] for r in search_res]) or "No data."
            else:
                output = "Invalid tool."
            logger.info(f"Tool '{tool_name}' executed successfully.")
        except Exception as e:
            output = f"Error: {str(e)}"
            logger.error(f"Tool validation failed: {str(e)}")
            
        tool_responses.append(ToolMessage(content=output, tool_call_id=tool_call["id"]))
    return {"messages": tool_responses}

async def data_evaluation_node(state: AgentGraphState):
    evaluator = llm.with_structured_output(FinalStructuredPayload)
    eval_prompt = "Review the context history and return the conversational summary alongside explicit confidence metrics."
    result = await evaluator.ainvoke([SystemMessage(content=eval_prompt)] + list(state["messages"]))
    return {"structured_response": result}

def route_next_step(state: AgentGraphState):
    if hasattr(state["messages"][-1], "tool_calls") and state["messages"][-1].tool_calls:
        return "execute_tools"
    return "run_evaluation"

# Compile Graph with Storage
workflow = StateGraph(AgentGraphState)
workflow.add_node("analyst_reasoner", analyst_reasoning_node)
workflow.add_node("execute_tools", tool_execution_node)
workflow.add_node("run_evaluation", data_evaluation_node)
workflow.add_edge(START, "analyst_reasoner")
workflow.add_conditional_edges("analyst_reasoner", route_next_step, {"execute_tools": "execute_tools", "run_evaluation": "run_evaluation"})
workflow.add_edge("execute_tools", "analyst_reasoner")
workflow.add_edge("run_evaluation", END)

memory_layer = MemorySaver()
compiled_graph = workflow.compile(checkpointer=memory_layer)

# ==========================================
# 4. FASTAPI WEB SERVER & SSE ROUTING
# ==========================================
app = FastAPI(title="Enterprise Data Agent SSE API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def sse_event_generator(user_message: str, thread_id: str):
    """Asynchronously iterates through LangGraph event streams to yield SSE formatting chunks."""
    config = {"configurable": {"thread_id": thread_id}}
    initial_input = {"messages": [HumanMessage(content=user_message)]}
    
    logger.info(f"Initiating stream request for thread session: {thread_id}")

    try:
        # Use v3 event streaming protocol to listen to internal updates and token chunks
        async for event in compiled_graph.astream_events(initial_input, config, version="v2"):
            kind = event.get("event")
            name = event.get("name")
            
            # Scenario A: The main router begins a Tool Call operation
            if kind == "on_chat_model_stream" and "tool_calls" in event["data"]["chunk"].additional_kwargs:
                tool_chunk = event["data"]["chunk"].additional_kwargs["tool_calls"]
                for tool in tool_chunk:
                    if "name" in tool and tool["name"]:
                        payload = {"event": "tool_start", "tool": tool["name"]}
                        yield f"data: {json.dumps(payload)}\n\n"
            
            # Scenario B: Raw token stream chunks arriving from the final text generations
            elif kind == "on_chat_model_stream" and name == "ChatOpenAI":
                content = event["data"]["chunk"].content
                if content:
                    payload = {"event": "token", "text": content}
                    yield f"data: {json.dumps(payload)}\n\n"
                    
            # Scenario C: Evaluation Node completes, yielding final structured validation dictionaries
            elif kind == "on_chain_end" and name == "run_evaluation":
                output_data = event["data"].get("output", {})
                if "structured_response" in output_data:
                    payload = {
                        "event": "metrics_evaluation",
                        "payload": output_data["structured_response"]
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    
    except Exception as stream_err:
        logger.error(f"Streaming anomaly detected: {str(stream_err)}")
        yield f"data: {json.dumps({'event': 'error', 'details': str(stream_err)})}\n\n"
    finally:
        logger.info(f"Stream generation closed for session thread: {thread_id}")
        yield "data: [DONE]\n\n"

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default_enterprise_thread"

@app.post("/api/chat/stream")
async def stream_chat_endpoint(payload: ChatRequest):
    """HTTP Post routing exposing the underlying async text/event-stream connection."""
    return StreamingResponse(
        sse_event_generator(payload.message, payload.thread_id),
        media_type="text/event-stream"
    )

if __name__ == "__main__":
    import uvicorn
    # Boot server locally on port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
