"""Application entry point: ``uvicorn app.main:app``."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.middleware import (
    BodySizeLimitMiddleware,
    ConcurrencyLimitMiddleware,
    CorrelationIdMiddleware,
)
from app.api.routes import get_optimize_service, router
from app.config import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Release the provider's pooled HTTP client on shutdown.

    Startup stays local-only: no provider call is made here, so a transient outage at the
    provider cannot stop the service from coming up and answering /health.
    """
    yield
    await get_optimize_service().aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="GridWise",
        version=__version__,
        description="LLM-assisted smart campus energy optimizer.",
        lifespan=lifespan,
    )

    # Starlette runs the most recently added middleware outermost, so this list is effectively
    # bottom-up: correlation ID first (so every rejection carries one), then the body-size
    # check (cheap, rejects before parsing), then the concurrency gate, which is where a
    # request may wait and where its time budget starts.
    app.add_middleware(ConcurrencyLimitMiddleware, settings=settings)
    app.add_middleware(BodySizeLimitMiddleware, settings=settings)
    app.add_middleware(CorrelationIdMiddleware)

    register_exception_handlers(app)
    app.include_router(router)
    return app


app = create_app()


__all__ = ["app", "create_app"]
