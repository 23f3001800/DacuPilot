import logging
import time
from contextlib import contextmanager
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("datapilot.latency")


@contextmanager
def track_latency(operation: str, metadata: dict[str, Any] | None = None):
    """Context manager that tracks and logs operation latency in milliseconds."""
    start = time.perf_counter()
    result = {"operation": operation, "start_time": start, "latency_ms": 0.0}
    try:
        yield result
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        result["latency_ms"] = round(elapsed_ms, 2)
        meta_str = f" {metadata}" if metadata else ""
        logger.info("LATENCY %s: %.2fms%s", operation, elapsed_ms, meta_str)


class LatencyMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware that logs request latency and injects X-Latency-Ms header."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "LATENCY %s %s: %.2fms (status=%d)",
            request.method,
            request.url.path,
            elapsed_ms,
            response.status_code,
        )
        response.headers["X-Latency-Ms"] = f"{elapsed_ms:.2f}"
        return response


def latency_middleware_factory():
    """Factory function returning the LatencyMiddleware class for app.add_middleware()."""
    return LatencyMiddleware
