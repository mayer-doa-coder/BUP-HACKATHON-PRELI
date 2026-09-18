"""Request-scoped middleware: correlation IDs and body-size protection.

Both are engineering concerns rather than organizer rules. The body limit exists because
every optimization request can trigger a paid LLM call, so it is set generously enough that
judge-shaped traffic is never affected.
"""

from __future__ import annotations

import asyncio
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.api.errors import CORRELATION_ID_HEADER, RequestTooLarge, error_response
from app.config import Settings
from app.services.deadline import Deadline

HEALTH_PATH = "/health"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Attach a correlation ID to every request and echo it on every response.

    Registered outermost so that even a rejection from the body-size middleware carries an
    ID the team can grep for in the logs.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = uuid.uuid4().hex
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response


class ConcurrencyLimitMiddleware(BaseHTTPMiddleware):
    """Bound the number of requests in flight, and start the request's time budget.

    The limit protects the provider quota and the process from a traffic spike, but it must
    never become a new failure mode: the cap is generous, and a request that arrives while the
    service is busy **queues rather than being rejected**. Only if it could no longer finish
    inside the organizer's 30 s window is it turned away with a 503.

    The deadline is started here, before queueing, so that time spent waiting counts against the
    same budget the pipeline uses. Starting it after the wait would let a queued request take
    28 s of work on top of its wait and blow the timeout.
    """

    def __init__(self, app, settings: Settings) -> None:  # noqa: ANN001 - Starlette's ASGI app type
        super().__init__(app)
        self._limit = max(1, settings.max_concurrent_requests)
        self._slots = asyncio.Semaphore(self._limit)
        self._budget_seconds = settings.hard_request_deadline_seconds

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # /health must answer even when the optimize path is saturated: the platform uses it to
        # decide whether this instance is alive, and queueing it would cause a pointless restart.
        if request.url.path == HEALTH_PATH:
            return await call_next(request)

        deadline = Deadline.start(self._budget_seconds)
        request.state.deadline = deadline

        try:
            await asyncio.wait_for(self._slots.acquire(), timeout=deadline.remaining())
        except TimeoutError:
            correlation_id = getattr(request.state, "correlation_id", uuid.uuid4().hex)
            return error_response(
                status_code=503,
                code="service_busy",
                message="The service is at capacity. Please retry.",
                correlation_id=correlation_id,
                details=[f"concurrent request limit is {self._limit}"],
            )

        try:
            return await call_next(request)
        finally:
            self._slots.release()


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject an oversized body before it is parsed.

    Only a declared ``Content-Length`` is inspected. A chunked upload without that header is
    passed through and bounded by the note-length check further down the pipeline.
    """

    def __init__(self, app, settings: Settings) -> None:  # noqa: ANN001 - Starlette's ASGI app type
        super().__init__(app)
        self._max_bytes = settings.max_request_body_bytes
        self._status = settings.oversized_request_status

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        declared_length = request.headers.get("content-length")
        if declared_length is not None:
            try:
                length = int(declared_length)
            except ValueError:
                length = 0
            if length > self._max_bytes:
                correlation_id = getattr(request.state, "correlation_id", uuid.uuid4().hex)
                return error_response(
                    status_code=self._status,
                    code=RequestTooLarge.code,
                    message="Request body exceeds the configured size limit.",
                    correlation_id=correlation_id,
                    details=[f"body limit is {self._max_bytes} bytes"],
                )
        return await call_next(request)


__all__ = [
    "HEALTH_PATH",
    "BodySizeLimitMiddleware",
    "ConcurrencyLimitMiddleware",
    "CorrelationIdMiddleware",
]
