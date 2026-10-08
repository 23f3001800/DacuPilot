import os
import json
import logging
from pathlib import Path
from typing import TypedDict, Annotated, Sequence, Literal
from pydantic import BaseModel, Field
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from .loader import load_real_world_excel
from .engine import PythonSandboxREPL
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
EXCEL_FILE_PATH = os.getenv(
    "EXCEL_FILE_PATH",
    str(Path(__file__).resolve().parent / "Inventory-Records-Sample-Data.xlsx"),
)
df, schema_context = load_real_world_excel(EXCEL_FILE_PATH)
sandbox_repl = PythonSandboxREPL(df)


def get_llm() -> ChatOpenAI:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required to run the Excel agent.")
    return ChatOpenAI(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        temperature=0.1,
        streaming=True,
    )


def get_tavily_client() -> TavilyClient:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is required to use web search.")
    return TavilyClient(api_key=api_key)

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
    llm = get_llm()
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
                search_res = get_tavily_client().search(
                    query=WebSearchInput(**raw_args).query,
                    max_results=2,
                ).get("results", [])
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
    llm = get_llm()
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
