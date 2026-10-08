import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from datapilot.config import get_config
from document_assistance.api import router as document_assistant_router
from document_intelligence.api import router as document_intelligence_router
from excel_agent.api import router as excel_agent_router
from fastapi import FastAPI
from fastapi.responses import FileResponse

from datapilot.latency import latency_middleware_factory

app = FastAPI(title="DocuPilot | Intelligent Document and Data Processing")
app.add_middleware(latency_middleware_factory())
app.include_router(excel_agent_router)
app.include_router(document_assistant_router)
app.include_router(document_intelligence_router)
UI_FILE = Path(__file__).resolve().parent / "ui" / "index.html"
DATA_UPLOAD_STYLESHEET = Path(__file__).resolve().parent / "ui" / "data-upload.css"


@app.get("/", include_in_schema=False)
async def app_ui():
    return FileResponse(UI_FILE)


@app.get("/ui/data-upload.css", include_in_schema=False)
async def data_upload_stylesheet():
    return FileResponse(DATA_UPLOAD_STYLESHEET, media_type="text/css")


@app.get("/api/health")
async def health():
    return {"status": "online"}


def configure_logging() -> None:
    settings = get_config()
    level = getattr(logging, settings.log_level, logging.INFO)
    file_handler = RotatingFileHandler(
        settings.log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s"
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logging.basicConfig(
        level=level,
        handlers=[console_handler, file_handler],
        force=True,
    )


if __name__ == "__main__":
    configure_logging()
    uvicorn.run(app, host="0.0.0.0", port=8000)
