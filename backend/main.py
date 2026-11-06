import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from datapilot.config import get_config
from document_assistance.api import router as document_assistant_router
from document_intelligence.api import router as document_intelligence_router
from excel_agent.api import router as excel_agent_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from datapilot.latency import latency_middleware_factory

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "DATAPILOT_ALLOWED_ORIGINS", "http://localhost:8080,http://localhost:5173"
    ).split(",")
    if origin.strip()
]
app = FastAPI(title="InsightPilot | Document and Data Workspace")
app.add_middleware(latency_middleware_factory())
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(excel_agent_router)
app.include_router(document_assistant_router)
app.include_router(document_intelligence_router)
FRONTEND_DIRECTORY = Path(__file__).resolve().parent.parent / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIRECTORY / "index.html"
app.mount("/assets", StaticFiles(directory=FRONTEND_DIRECTORY / "assets", check_dir=False), name="frontend-assets")


@app.get("/", include_in_schema=False)
async def app_ui():
    if not FRONTEND_INDEX.is_file():
        return HTMLResponse(
            "<!doctype html><html><head><title>InsightPilot</title></head><body>"
            "<h1>The workspace build is unavailable</h1>"
            "<p>Run npm ci and npm run build in the frontend directory, then restart the backend.</p>"
            "</body></html>",
            status_code=503,
        )
    return FileResponse(FRONTEND_INDEX)


@app.get("/favicon.svg", include_in_schema=False)
async def app_favicon():
    return FileResponse(FRONTEND_DIRECTORY / "favicon.svg", media_type="image/svg+xml")


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
