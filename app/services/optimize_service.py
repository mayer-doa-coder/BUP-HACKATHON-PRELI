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
from app.cache.request_cache import TtlLruCache, build_cache, response_cache_key
from app.config import Settings, get_settings
from app.llm.interpreter import LlmDirectiveInterpreter, build_interpreter
from app.llm.repair import InterpretationRun, build_runner
from app.optimizer.hybrid_solve import SolveOutcome, SolveStatus, hybrid_solve, screen_baseline_feasibility
from app.optimizer.result import build_hourly_plan
from app.schemas.directive import DirectiveInterpretation
from app.schemas.request import OptimizeRequest
from app.schemas.response import OptimizeResponse
from app.services.deadline import Deadline
from app.services.plan_summary import build_plan_summary
from app.validation.replay import ValidationReport, replay
from app.validation.request_semantics import check_note_length_limits, check_request_semantics
from app.validation.totals import recalculate_totals


class OptimizeService:
    """Owns the per-request pipeline. Stateless apart from its settings and interpreter."""

    def __init__(
        self,
        settings: Settings | None = None,
        interpreter: LlmDirectiveInterpreter | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        # Built once, not per request: the provider holds a pooled HTTP client, and a fresh TLS
        # handshake on every judged call would eat into the latency budget for nothing.
        self._interpreter = interpreter if interpreter is not None else build_interpreter(self._settings)
        self._runner = build_runner(self._interpreter, self._settings)
        self._response_cache: TtlLruCache[OptimizeResponse] = build_cache(self._settings)
        #: Telemetry from the most recent interpretation, for the observability layer (P15).
        self._last_run: InterpretationRun | None = None

    @property
    def response_cache(self) -> TtlLruCache[OptimizeResponse]:
        return self._response_cache

    @property
    def interpreter(self) -> LlmDirectiveInterpreter | None:
        return self._interpreter

    @property
    def last_run(self) -> InterpretationRun | None:
        return self._last_run

    async def aclose(self) -> None:
        if self._interpreter is not None:
            await self._interpreter.aclose()

    async def run(
        self,
        request: OptimizeRequest,
        deadline: Deadline | None = None,
    ) -> OptimizeResponse:
        # The deadline may already have been started by the middleware, so that time spent
        # queueing behind the concurrency limit counts against the same 30 s the judge allows.
        deadline = deadline or Deadline.start(self._settings.hard_request_deadline_seconds)

        self.validate(request)

        cache_key = response_cache_key(request, self._settings)
        cached = self._response_cache.get(cache_key)
        if cached is not None:
            # Stored only after independent replay accepted it, so serving it needs no rework.
            return cached

        # Before the paid call: an impossible scenario is rejected here, and — just as
        # importantly — proving it schedulable is what makes a later infeasibility evidence
        # about the *interpretation* rather than about the request.
        self.screen_feasibility(request)

        directives = await self.interpret(request, deadline)
        outcome, directives = await self._solve_with_feasibility_retry(request, directives, deadline)

        self._raise_for_solve_status(outcome)
        response = self._finalize(request, directives, outcome)
        # Only a replay-validated response reaches this line; _finalize raises otherwise.
        self._response_cache.set(cache_key, response)
        return response

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

    async def interpret(
        self,
        request: OptimizeRequest,
        deadline: Deadline | None = None,
    ) -> list[DirectiveInterpretation]:
        """Interpret the operator notes with the language model.

        There is deliberately no keyword-matching fallback. A regex interpreter would defeat the
        mandatory-LLM requirement outright, so when the model is unusable this fails closed
        rather than guessing. The bounded, failure-class-specific retry policy lands in P10;
        today a single attempt is made and any failure becomes a controlled error.
        """
        if self._runner is None:
            raise InterpretationUnavailable("the directive interpreter is not configured")

        deadline = deadline or Deadline.start(self._settings.hard_request_deadline_seconds)
        run = await self._runner.run(request, deadline)
        self._last_run = run

        if not run.ok:
            raise InterpretationUnavailable(
                "The operator notes could not be interpreted.",
                details=run.failure_codes or [run.last_error or "interpretation failed"],
            )
        return run.directives

    def solve_and_build(
        self,
        request: OptimizeRequest,
        directives: Sequence[DirectiveInterpretation],
    ) -> OptimizeResponse:
        """Compile, solve, canonicalize, replay, and return — or fail in a controlled way.

        The synchronous path, used by the regression runner and by anything that already holds
        validated directives. ``run()`` adds the feasibility reinterpretation around it.
        """
        outcome = hybrid_solve(request, directives, self._settings)
        self._raise_for_solve_status(outcome)
        return self._finalize(request, directives, outcome)

    async def _solve_with_feasibility_retry(
        self,
        request: OptimizeRequest,
        directives: Sequence[DirectiveInterpretation],
        deadline: Deadline,
    ) -> tuple[SolveOutcome, Sequence[DirectiveInterpretation]]:
        """Solve, and on directive infeasibility allow exactly one focused reinterpretation.

        The baseline screen already proved the scenario schedulable, so an infeasible result
        points at the interpretation. The retry re-reads the original notes; it never relaxes a
        constraint to manufacture feasibility. If the second reading is also infeasible, the
        *first* outcome is kept and reported — a second wrong answer is not an improvement.
        """
        outcome = hybrid_solve(request, directives, self._settings)
        if outcome.status is not SolveStatus.DIRECTIVE_INFEASIBLE or self._runner is None:
            return outcome, directives

        retry = await self._runner.reinterpret_for_feasibility(request, deadline)
        self._last_run = retry
        if not retry.ok:
            return outcome, directives

        retry_outcome = hybrid_solve(request, retry.directives, self._settings)
        if retry_outcome.ok:
            # Replace the cached interpretation with the corrected one, so an identical request
            # does not pay for the same reinterpretation again. It passed the same guardrails.
            self._runner.remember(request, retry.directives)
            return retry_outcome, retry.directives
        return outcome, directives

    def _finalize(
        self,
        request: OptimizeRequest,
        directives: Sequence[DirectiveInterpretation],
        outcome: SolveOutcome,
    ) -> OptimizeResponse:
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
