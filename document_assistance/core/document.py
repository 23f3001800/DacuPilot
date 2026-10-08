import os
from pathlib import Path
from typing import TypedDict, Annotated, Sequence
from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from .loader import KnowledgeSection, load_docx_sections

load_dotenv()


# 1. State Definition (Tracks conversation, history summary, and active topic)
class AssistantState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    session_summary: str      # Tracks what information has ALREADY been explained
    current_topic: str        # Tracks active focus to handle graceful switching

KNOWLEDGE_DOCUMENT = (
    Path(__file__).resolve().parents[1]
    / "knowledge_base"
    / "Questions.docx"
)
KNOWLEDGE_SECTIONS = load_docx_sections(KNOWLEDGE_DOCUMENT)


def get_llm() -> ChatOpenAI:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required to run the document assistant.")
    return ChatOpenAI(
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        temperature=0.0,
    )


def _detect_topic(question: str) -> str:
    normalized = question.casefold()
    if any(term in normalized for term in ("excel", "spreadsheet", "inventory", "dataframe")):
        return "Excel data analysis"
    if any(
        term in normalized
        for term in ("aadhaar", "pan card", "ifsc", "handwritten", "ocr", "document type")
    ):
        return "Document intelligence"
    return "Document support"


def _format_knowledge(sections: Sequence[KnowledgeSection]) -> str:
    return "\n\n".join(
        f"Source: [{section.citation}]\n{section.text}"
        for section in sections
    )


def document_assistant_node(state: AssistantState):
    latest_message = state["messages"][-1]
    question = str(latest_message.content)
    previous_topic = state.get("current_topic", "")
    current_topic = _detect_topic(question)
    topic_instruction = (
        "The user has switched topics. Acknowledge the change briefly."
        if previous_topic and previous_topic != current_topic
        else "Continue the current topic."
    )
    db_context = _format_knowledge(KNOWLEDGE_SECTIONS)

    system_prompt = SystemMessage(content=f"""
You are a document-aware assistant. Answer only from the supplied source text.
If the sources do not contain the answer, say so instead of guessing.
Use conversation history to remember what the user asked and what you already explained.
Avoid repeating prior explanations; add only relevant new information.
{topic_instruction}

Knowledge base:
{db_context}

End each factual answer with a source citation in the exact format
"Source: [Questions.docx — section name]". Cite only a section that supports the answer.
""")

    response = get_llm().invoke([system_prompt] + list(state["messages"]))
    previous_summary = state.get("session_summary", "")
    summary_entry = f"User asked: {question}. Assistant answered: {response.content}"

    return {
        "messages": [response],
        "session_summary": "\n".join(
            entry for entry in (previous_summary, summary_entry) if entry
        ),
        "current_topic": current_topic,
    }


# Build out the State Graph
workflow = StateGraph(AssistantState)
workflow.add_node("assistant", document_assistant_node)
workflow.add_edge(START, "assistant")
workflow.add_edge("assistant", END)

compiled_agent = workflow.compile(checkpointer=MemorySaver())
