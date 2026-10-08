import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .core.document import USER_DOCUMENTS, compiled_agent
from .core.loader import extract_uploaded_document

logger = logging.getLogger("datapilot.document_assistant.api")
router = APIRouter(prefix="/api/document-assistant", tags=["document assistant"])
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_TOTAL_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_DOCUMENTS_PER_REQUEST = 10


class DocumentChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)


@router.post("/chat")
async def document_chat(payload: DocumentChatRequest):
    try:
        thread_id = str(UUID(payload.thread_id))
    except ValueError:
        thread_id = payload.thread_id
    config = {"configurable": {"thread_id": thread_id}}
    try:
        result = await run_in_threadpool(
            compiled_agent.invoke,
            {
                "messages": [HumanMessage(content=payload.message)],
                "session_id": thread_id,
            },
            config,
        )
        response = result["messages"][-1]
        return {
            "thread_id": thread_id,
            "answer": response.content,
            "topic": result.get("current_topic", ""),
        }
    except Exception as error:
        logger.exception(
            "Document-assistant request failed for thread %s", payload.thread_id
        )
        raise HTTPException(
            status_code=502,
            detail="The document assistant failed. Check the server log for details.",
        ) from error


@router.post("/documents")
async def upload_session_documents(
    thread_id: str = Form(min_length=1),
    external_processing_consent: bool = Form(False),
    files: list[UploadFile] = File(..., min_length=1),
):
    try:
        session_id = str(UUID(thread_id))
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="Use a valid session UUID for private document uploads.",
        ) from error
    if len(files) > MAX_DOCUMENTS_PER_REQUEST:
        raise HTTPException(
            status_code=400,
            detail=f"Upload no more than {MAX_DOCUMENTS_PER_REQUEST} documents at once.",
        )
    if not external_processing_consent:
        raise HTTPException(
            status_code=400,
            detail=(
                "Consent is required because retrieved document text may be sent "
                "to the configured external language model when you ask a question."
            ),
        )

    extracted_documents = []
    total_bytes = 0
    for upload in files:
        if not upload.filename:
            raise HTTPException(
                status_code=400,
                detail="Every uploaded document needs a filename.",
            )
        filename = Path(upload.filename.replace("\\", "/")).name
        content = await upload.read(MAX_DOCUMENT_BYTES + 1)
        if len(content) > MAX_DOCUMENT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"{filename} exceeds the 20 MB limit.",
            )
        total_bytes += len(content)
        if total_bytes > MAX_TOTAL_DOCUMENT_BYTES:
            raise HTTPException(
                status_code=413,
                detail="The combined upload exceeds the 20 MB request limit.",
            )
        try:
            pages = await run_in_threadpool(
                extract_uploaded_document,
                filename,
                content,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            logger.exception("Document text extraction is unavailable")
            raise HTTPException(
                status_code=503,
                detail="Document text extraction is unavailable on this server.",
            ) from error
        extracted_documents.append((filename, pages))

    try:
        indexed = USER_DOCUMENTS.add_documents(session_id, extracted_documents)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    logger.info(
        "Indexed %s private document(s) for session %s",
        len(indexed),
        session_id,
    )
    return {
        "thread_id": session_id,
        "documents": [
            {
                "filename": filename,
                **metadata,
            }
            for (filename, _), metadata in zip(extracted_documents, indexed)
        ],
    }


@router.delete("/session/{thread_id}")
async def clear_session(thread_id: str):
    try:
        session_id = str(UUID(thread_id))
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="Use a valid session UUID to clear private documents.",
        ) from error
    removed_chunks = USER_DOCUMENTS.clear_session(session_id)
    checkpointer = compiled_agent.checkpointer
    delete_thread = getattr(checkpointer, "delete_thread", None)
    if delete_thread is not None:
        await run_in_threadpool(delete_thread, session_id)
    logger.info("Cleared Document Assistant session %s", session_id)
    return {
        "thread_id": session_id,
        "removed_chunks": removed_chunks,
        "conversation_cleared": delete_thread is not None,
    }
