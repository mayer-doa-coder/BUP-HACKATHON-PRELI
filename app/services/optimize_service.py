"""Orchestration for ``POST /optimize-energy``.

The full pipeline::

    validate -> baseline feasibility LP -> LLM interpretation -> deterministic guardrails
    -> directive compiler -> LP relaxation -> authoritative MILP -> canonicalize
    -> serialize -> parse back -> independent replay -> response

Every stage exists except the interpreter and its guardrails (P8/P9), which sit behind the
``interpret`` seam. Everything downstream of that seam is live and is exercised today by
feeding ground-truth directives straight into :meth:`OptimizeService.solve_and_build`.

Two rules shape this module:

* **Nothing is returned that has not been replayed.** The response is serialized, parsed back,
  and validated by the independent replay validator before it leaves. A replay failure is an
  invariant failure: controlled 500, never a retry, never an HTTP 200.
* **Failure classes stay distinct.** The solver returns statuses rather than raising, and this
  is the one place where they become HTTP outcomes.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.api.errors import (
    DirectiveInfeasible,
    InterpretationUnavailable,
    ReplayInvariantFailure,
    RequestTooLarge,
    SemanticallyInvalidRequest,
    SolverFailure,
)
from app.config import Settings, get_settings
from app.optimizer.hybrid_solve import SolveOutcome, SolveStatus, hybrid_solve, screen_baseline_feasibility
from app.optimizer.result import build_hourly_plan
from app.schemas.directive import DirectiveInterpretation
from app.schemas.request import OptimizeRequest
from app.schemas.response import OptimizeResponse
from app.services.plan_summary import build_plan_summary
from app.validation.replay import ValidationReport, replay
from app.validation.request_semantics import check_note_length_limits, check_request_semantics
from app.validation.totals import recalculate_totals


class OptimizeService:
    """Owns the per-request pipeline. Stateless apart from its settings and interpreter."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def run(self, request: OptimizeRequest) -> OptimizeResponse:
        self.validate(request)
        self.screen_feasibility(request)
        directives = await self.interpret(request)
        return self.solve_and_build(request, directives)

    # ------------------------------------------------------------------ stages

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

    def screen_feasibility(self, request: OptimizeRequest) -> None:
        """Reject an impossible scenario before spending a paid LLM call.

        Running this *before* interpretation is what makes a later infeasibility meaningful: if
        the scenario is schedulable on its own, an infeasible result afterwards points at the
        interpretation rather than at the request.
        """
        screen = screen_baseline_feasibility(request, self._settings)
        if not screen.feasible:
            raise SemanticallyInvalidRequest(
                "The scenario cannot be scheduled even before any operator directive is applied.",
                details=[f"baseline LP status: {screen.lp.status}"],
            )

    async def interpret(self, request: OptimizeRequest) -> list[DirectiveInterpretation]:
        """Seam for the LLM interpreter (P8) and its deterministic guardrails (P9).

        Deliberately not implemented with a keyword matcher: a regex fallback would defeat the
        mandatory-LLM requirement outright, so until the interpreter lands this fails closed.
        """
        raise InterpretationUnavailable("the directive interpreter is not configured")

    def solve_and_build(
        self,
        request: OptimizeRequest,
        directives: Sequence[DirectiveInterpretation],
    ) -> OptimizeResponse:
        """Compile, solve, canonicalize, replay, and return — or fail in a controlled way."""
        outcome = hybrid_solve(request, directives, self._settings)
        self._raise_for_solve_status(outcome)

        response, report = self._build_validated_response(request, directives, outcome)
        if response is None:
            raise ReplayInvariantFailure(
                "The computed schedule failed independent replay.",
                details=list(report.codes) if report is not None else [],
            )
        return response

    # ------------------------------------------------------------------ internals

    def _raise_for_solve_status(self, outcome: SolveOutcome) -> None:
        if outcome.status is SolveStatus.OK:
            return
        if outcome.status is SolveStatus.BASELINE_INFEASIBLE:
            raise SemanticallyInvalidRequest(
                "The scenario cannot be scheduled.",
                details=list(outcome.detail),
            )
        if outcome.status is SolveStatus.DIRECTIVE_INFEASIBLE:
            # P10 attempts one focused semantic reparse before this point. Constraints are never
            # weakened to manufacture feasibility.
            raise DirectiveInfeasible(
                "The interpreted directives cannot be satisfied for this scenario.",
                details=list(outcome.detail),
            )
        raise SolverFailure("The optimizer could not produce a schedule.", details=list(outcome.detail))

    def _build_validated_response(
        self,
        request: OptimizeRequest,
        directives: Sequence[DirectiveInterpretation],
        outcome: SolveOutcome,
    ) -> tuple[OptimizeResponse | None, ValidationReport | None]:
        """Build, serialize, parse back, and replay — loosening precision only if forced to.

        Rounding the independent decisions keeps the response readable, but on an input with
        unusually long decimals the rounded battery movements stop cancelling over the day and
        the end-of-day balance drifts past the internal tolerance. Rather than fail such a
        request, the plan is rebuilt at finer precision and finally at full precision. Every
        rung is deterministic and none of them changes any semantics — only how many decimal
        places the independent decisions carry.
        """
        coarse = self._settings.response_decimal_places
        precision_ladder = (coarse, coarse + 3, None)

        report: ValidationReport | None = None
        for decimals in precision_ladder:
            candidate = self._assemble(request, directives, outcome, decimals=decimals)
            # Replay the parsed-back representation, which is exactly what the judge will read.
            parsed = OptimizeResponse.model_validate_json(candidate.model_dump_json())
            report = replay(request, directives, parsed, settings=self._settings)
            if report.ok:
                return parsed, report
        return None, report

    def _assemble(
        self,
        request: OptimizeRequest,
        directives: Sequence[DirectiveInterpretation],
        outcome: SolveOutcome,
        *,
        decimals: int | None,
    ) -> OptimizeResponse:
        plan = build_hourly_plan(
            request,
            outcome.compiled,
            outcome.solution,
            decimals=decimals,
            settings=self._settings,
        )
        tariff_by_hour = {entry.hour: entry.tariff_bdt_per_kwh for entry in request.canonical_hours()}
        totals = recalculate_totals(plan, tariff_by_hour)

        return OptimizeResponse(
            scenario_id=request.scenario_id,
            directive_interpretation=list(directives),
            hourly_plan=plan,
            total_grid_kwh=totals.total_grid_kwh,
            total_cost_bdt=totals.total_cost_bdt,
            peak_grid_kwh=totals.peak_grid_kwh,
            plan_summary=build_plan_summary(directives, plan),
        )


__all__ = ["OptimizeService"]
