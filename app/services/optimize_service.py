"""Orchestration for ``POST /optimize-energy``.

The full pipeline is:

    validate -> baseline feasibility LP -> LLM interpretation -> deterministic guardrails
    -> directive compiler -> LP relaxation -> authoritative MILP -> canonicalize
    -> independent replay -> response

Phase P1 builds the first stage only. Request validation and the 400/422 boundary are live;
every stage after that is added in its own phase, in the order above. A valid request
therefore currently ends in a controlled ``PipelineNotImplemented`` (500) rather than a
fabricated plan — the service never invents a schedule it did not actually compute.
"""

from __future__ import annotations

from app.api.errors import PipelineNotImplemented, RequestTooLarge, SemanticallyInvalidRequest
from app.config import Settings, get_settings
from app.schemas.request import OptimizeRequest
from app.schemas.response import OptimizeResponse
from app.validation.request_semantics import check_note_length_limits, check_request_semantics


class OptimizeService:
    """Owns the per-request pipeline. Stateless apart from its settings."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def run(self, request: OptimizeRequest) -> OptimizeResponse:
        self.validate(request)
        raise PipelineNotImplemented("optimization pipeline is not wired up yet")

    def validate(self, request: OptimizeRequest) -> None:
        """Resource limits first, then scenario semantics.

        Both run before anything expensive: no LLM call and no solver call is made for a
        request that is already known to be unusable.
        """
        oversized_notes = check_note_length_limits(request, self._settings)
        if oversized_notes:
            raise RequestTooLarge(
                "Operator note exceeds the configured size limit.",
                details=oversized_notes,
                http_status=self._settings.oversized_request_status,
            )

        violations = check_request_semantics(request, self._settings)
        if violations:
            raise SemanticallyInvalidRequest(
                "The request is well formed but describes an invalid scenario.",
                details=violations,
            )


__all__ = ["OptimizeService"]
