import sys
import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

log = structlog.get_logger()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = None
        exc_info_triple = None
        try:
            response = await call_next(request)
        except Exception:
            exc_info_triple = sys.exc_info()
            raise
        finally:
            if exc_info_triple is None:
                latency_ms = round((time.perf_counter() - start) * 1000)
                log.info(
                    "request",
                    method=request.method,
                    path=request.url.path,
                    status=response.status_code,
                    latency_ms=latency_ms,
                )
            else:
                latency_ms = round((time.perf_counter() - start) * 1000)
                log.info(
                    "request",
                    method=request.method,
                    path=request.url.path,
                    status=500,
                    latency_ms=latency_ms,
                    exc_info=exc_info_triple,
                )
        return response
