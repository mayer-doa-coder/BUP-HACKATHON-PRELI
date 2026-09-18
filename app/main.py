"""Application entry point: ``uvicorn app.main:app``."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.middleware import BodySizeLimitMiddleware, CorrelationIdMiddleware
from app.api.routes import router
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="GridWise",
        version=__version__,
        description="LLM-assisted smart campus energy optimizer.",
    )

    # Starlette runs the most recently added middleware outermost, so the correlation ID is
    # attached before the size check and is therefore present on a rejection too.
    app.add_middleware(BodySizeLimitMiddleware, settings=settings)
    app.add_middleware(CorrelationIdMiddleware)

    register_exception_handlers(app)
    app.include_router(router)
    return app


app = create_app()


__all__ = ["app", "create_app"]
