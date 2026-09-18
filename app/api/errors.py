"""Controlled error taxonomy and the HTTP status mapping.

FastAPI answers body-validation failures with 422 by default, but the Problem Statement §6.1
defines 400 for a malformed or structurally invalid request and reserves 422 for a well-formed
request that is semantically invalid. The handlers registered here override that default.

Nothing in this module may leak a stack trace, a prompt, a provider payload, or a secret.
A 500 carries a correlation ID and a failure code — never an internal message.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("gridwise.errors")

# A validation failure can list dozens of field errors; only the first few are echoed.
MAX_REPORTED_DETAILS = 10

CORRELATION_ID_HEADER = "X-Correlation-ID"


class GridWiseError(Exception):
    """Base class for every failure the service raises deliberately."""

    http_status: int = 500
    code: str = "internal_error"
    # Whether ``details`` may be echoed to the caller. Never true for internal failures.
    expose_details: bool = False

    def __init__(
        self,
        message: str,
        *,
        details: list[str] | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []
        if http_status is not None:
            # Lets a configurable policy (for example the oversized-request status) override
            # the class default without introducing a second exception type.
            self.http_status = http_status


class StructurallyInvalidRequest(GridWiseError):
    """Malformed JSON, wrong types, wrong shapes, bad hour set."""

    http_status = 400
    code = "invalid_request"
    expose_details = True


class SemanticallyInvalidRequest(GridWiseError):
    """Well-formed request describing an impossible scenario."""

    http_status = 422
    code = "unprocessable_scenario"
    expose_details = True


class RequestTooLarge(GridWiseError):
    """Body or note beyond the configured resource-protection limit."""

    http_status = 413
    code = "request_too_large"
    expose_details = True


class InterpretationUnavailable(GridWiseError):
    """The LLM could not produce usable structured output within the attempt budget."""

    code = "interpretation_unavailable"


class SolverFailure(GridWiseError):
    """LP or MILP returned a non-optimal status, or an optimizer invariant broke."""

    code = "solver_failure"


class ReplayInvariantFailure(GridWiseError):
    """The serialized response failed independent replay. Never retried, never returned as 200."""

    code = "replay_invariant_failure"


class PipelineNotImplemented(GridWiseError):
    """A pipeline stage that has not been built yet. Removed once the pipeline is complete."""

    code = "not_implemented"


def correlation_id_of(request: Request) -> str:
    """The request's correlation ID, or a fresh one if the middleware did not run."""
    existing = getattr(request.state, "correlation_id", None)
    return existing if isinstance(existing, str) and existing else uuid.uuid4().hex


def error_payload(
    *,
    code: str,
    message: str,
    correlation_id: str,
    details: list[str] | None = None,
) -> dict[str, Any]:
    """The single error envelope used by every failure path, including the middleware."""
    error: dict[str, Any] = {"code": code, "message": message, "correlation_id": correlation_id}
    if details:
        error["details"] = details[:MAX_REPORTED_DETAILS]
    return {"error": error}


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    correlation_id: str,
    details: list[str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=error_payload(code=code, message=message, correlation_id=correlation_id, details=details),
        headers={CORRELATION_ID_HEADER: correlation_id},
    )


def _sanitize_validation_errors(exc: RequestValidationError) -> list[str]:
    """Field path + reason only.

    Pydantic's raw error dicts carry the offending ``input`` value and context; those are
    dropped so that an oversized or sensitive body is never reflected back to the caller.
    """
    details: list[str] = []
    for error in exc.errors()[:MAX_REPORTED_DETAILS]:
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        message = str(error.get("msg", "invalid value"))
        details.append(f"{location}: {message}" if location else message)
    return details


def register_exception_handlers(app: FastAPI) -> None:
    """Install every handler. Order does not matter; FastAPI dispatches by exception type."""

    @app.exception_handler(RequestValidationError)
    async def _handle_request_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # This is the override that turns FastAPI's default 422 into the contract's 400.
        correlation_id = correlation_id_of(request)
        details = _sanitize_validation_errors(exc)
        logger.info(
            "structurally invalid request",
            extra={"correlation_id": correlation_id, "error_count": len(exc.errors())},
        )
        return error_response(
            status_code=400,
            code=StructurallyInvalidRequest.code,
            message="Malformed or structurally invalid request.",
            correlation_id=correlation_id,
            details=details,
        )

    @app.exception_handler(GridWiseError)
    async def _handle_gridwise_error(request: Request, exc: GridWiseError) -> JSONResponse:
        correlation_id = correlation_id_of(request)
        is_server_error = exc.http_status >= 500
        logger.log(
            logging.ERROR if is_server_error else logging.INFO,
            "request failed: %s",
            exc.code,
            extra={"correlation_id": correlation_id, "http_status": exc.http_status},
        )
        return error_response(
            status_code=exc.http_status,
            code=exc.code,
            # An internal failure never describes itself to the caller.
            message=exc.message if not is_server_error else "Internal error.",
            correlation_id=correlation_id,
            details=exc.details if exc.expose_details else None,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Keeps 404/405 and friends inside the same envelope as everything else.
        correlation_id = correlation_id_of(request)
        return error_response(
            status_code=exc.status_code,
            code="http_error",
            message=str(exc.detail),
            correlation_id=correlation_id,
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = correlation_id_of(request)
        # exc_info stays in the server log; the caller sees only the correlation ID.
        logger.exception("unhandled error", extra={"correlation_id": correlation_id})
        return error_response(
            status_code=500,
            code="internal_error",
            message="Internal error.",
            correlation_id=correlation_id,
        )


__all__ = [
    "CORRELATION_ID_HEADER",
    "GridWiseError",
    "InterpretationUnavailable",
    "PipelineNotImplemented",
    "ReplayInvariantFailure",
    "RequestTooLarge",
    "SemanticallyInvalidRequest",
    "SolverFailure",
    "StructurallyInvalidRequest",
    "correlation_id_of",
    "error_payload",
    "error_response",
    "register_exception_handlers",
]
