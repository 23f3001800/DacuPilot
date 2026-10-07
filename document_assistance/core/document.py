import os
from typing import TypedDict, Annotated, Sequence
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

# 1. State Definition (Tracks conversation, history summary, and active topic)
class AssistantState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    session_summary: str      # Tracks what information has ALREADY been explained
    current_topic: str        # Tracks active focus to handle graceful switching

# 2. Mock Document Database (Representing parsed document chunks with IDs)
DOCUMENT_DB = {
    "sec_1_billing": "[Section 1.1: Billing Cycle] Invoices are generated automatically on the 1st of every month. Users have a 14-day grace period to settle payment before account suspension occurs.",
    "sec_2_refunds": "[Section 2.3: Refund Eligibility] Refunds are only valid within 30 days of the original purchase. Custom enterprise tier add-ons are strictly non-refundable.",
    "sec_3_api": "[Section 3.7: API Limits] Standard API keys are rate-limited to 60 requests per minute. Custom endpoints scale up to 5,000 requests per minute on Enterprise plans."
}

# 3. Core Reasoning Node
llm = ChatOpenAI(model="gpt-4o", temperature=0.0)

def document_assistant_node(state: AssistantState):
    # Retrieve structural database context
    db_context = "\n".join([f"ID: {k} -> Content: {v}" for k, v in DOCUMENT_DB.items()])
    
    system_prompt = SystemMessage(content=f"""
You are a document-aware enterprise support assistant.
Here is the official documentation knowledge base you have access to:
{db_context}

CRITICAL RULES:
1. Review the existing Session Summary: "{state.get('session_summary', 'None')}"
2. DO NOT repeat any details, facts, or instructions listed in that session summary.
3. If the user changes the subject, explicitly acknowledge the topic switch.
4. You MUST append an exact citation header format at the end of your response specifying the document section name, e.g., "Source: [Section X.Y: Title]".
""")
    
    response = llm.invoke([system_prompt] + list(state["messages"]))
    
    # Simple internal logic to update the tracking state parameters dynamically
    new_summary = state.get("session_summary", "") + f" | User asked about: {state['messages'][-1].content}. Agent provided: {response.content[:60]}..."
    
    return {
        "messages": [response],
        "session_summary": new_summary
    }

# Build out the State Graph
workflow = StateGraph(AssistantState)
workflow.add_node("assistant", document_assistant_node)
workflow.add_edge(START, "assistant")
workflow.add_edge("assistant", END)

compiled_agent = workflow.compile(checkpointer=MemorySaver())
