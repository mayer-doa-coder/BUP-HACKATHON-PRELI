"""The two judge-facing endpoints. Nothing else belongs on this router.

Demo and diagnostic routes live on a separate router behind ``DEMO_MODE`` (P18) so the
judged surface stays exactly what the Problem Statement §06 defines.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from app.observability.metrics import render_metrics
from app.schemas.request import OptimizeRequest
from app.schemas.response import OptimizeResponse
from app.services.optimize_service import OptimizeService

router = APIRouter()

_service = OptimizeService()


def get_optimize_service() -> OptimizeService:
    """Dependency seam so tests can substitute a service without patching module globals."""
    return _service


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Readiness only.

    Deliberately makes no LLM and no solver call: a transient provider timeout must not make
    the process itself look dead. Provider health belongs in telemetry, not here.
    """
    return {"status": "ok"}


ServiceDependency = Annotated[OptimizeService, Depends(get_optimize_service)]


@router.post("/optimize-energy", response_model=OptimizeResponse, tags=["optimize"])
async def optimize_energy(
    payload: OptimizeRequest,
    service: ServiceDependency,
    http_request: Request,
) -> OptimizeResponse:
    # The concurrency middleware starts the budget before queueing, so the pipeline inherits it
    # rather than starting a fresh 28 s after an unknown wait.
    deadline = getattr(http_request.state, "deadline", None)
    return await service.run(payload, deadline=deadline)


__all__ = ["get_optimize_service", "router"]


# Operational surface, kept on a separate router so the judged contract stays exactly the two
# endpoints above. Included by `create_app` only when METRICS_ENABLED is set.
metrics_router = APIRouter()


@metrics_router.get("/metrics", include_in_schema=False, tags=["operations"])
async def prometheus_metrics() -> Response:
    """Prometheus text exposition. Never called by the judge; used for latency and failure watch."""
    return Response(content=render_metrics(), media_type="text/plain; version=0.0.4; charset=utf-8")
