"""Builds the demo views by running the real pipeline.

Nothing here re-implements the pipeline; it runs the production one and then reads the artefacts
the earlier phases already produce — the compiler's `ConstraintTrace` provenance (P3), the
solver statuses (P5), and the replay residuals (P2). That matters: a demo that computed its own
numbers could show a valid-looking story while the judged path did something else.

The demo is allowed to be slower and richer than the judge path. It must never change it.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

from app.config import Settings, get_settings
from app.demo.models import (
    AnalysisResponse,
    ConstraintOrigin,
    CostComparison,
    HourDetail,
    NoteInterpretationView,
    ParaphraseVariant,
    SolverDiagnostics,
    ValidationProof,
)
from app.optimizer.compile_directives import CompiledConstraints, compile_directives
from app.optimizer.hybrid_solve import SolveOutcome, hybrid_solve
from app.schemas.directive import DirectiveInterpretation
from app.schemas.request import OptimizeRequest
from app.schemas.response import OptimizeResponse
from app.validation.replay import replay

#: A value within this of a bound is treated as binding, for the "why this hour" view.
BINDING_TOLERANCE = 1e-6


def build_analysis(
    request: OptimizeRequest,
    directives: Sequence[DirectiveInterpretation],
    response: OptimizeResponse,
    outcome: SolveOutcome,
    *,
    elapsed_ms: float = 0.0,
    interpretation_source: str = "llm",
    settings: Settings | None = None,
) -> AnalysisResponse:
    settings = settings or get_settings()
    compiled = outcome.compiled or compile_directives(request, directives, settings)
    hours = request.canonical_hours()
    plan = sorted(response.hourly_plan, key=lambda entry: entry.hour)

    report = replay(request, directives, response, settings=settings)

    return AnalysisResponse(
        scenario_id=response.scenario_id,
        interpretation=_interpretation_views(request, directives),
        directives=list(directives),
        hours=[
            _hour_detail(index, hours[index], plan[index], compiled) for index in range(len(plan))
        ],
        plan=plan,
        totals_grid_kwh=response.total_grid_kwh,
        totals_cost_bdt=response.total_cost_bdt,
        peak_grid_kwh=response.peak_grid_kwh,
        plan_summary=response.plan_summary,
        solver=_solver_diagnostics(outcome, settings),
        validation=ValidationProof(
            passed=report.ok,
            max_energy_balance_error=report.max_balance_error,
            max_battery_transition_error=report.max_state_error,
            final_state_of_charge_error=report.final_energy_error,
            recalculated_total_grid_kwh=report.recalculated_total_grid_kwh,
            recalculated_total_cost_bdt=report.recalculated_total_cost_bdt,
            recalculated_peak_grid_kwh=report.recalculated_peak_grid_kwh,
            violations=report.messages,
        ),
        cost_comparison=build_cost_comparison(request, compiled, response, settings),
        constraint_origins=[
            ConstraintOrigin(
                hour=item.hour,
                field=item.field,
                source_note_index=item.source_note_index,
                directive_type=item.directive_type,
                original_value=item.original_value,
                effective_value=item.effective_value,
            )
            for item in compiled.trace
        ],
        ambiguity_flags=list(compiled.ambiguity_flags),
        interpretation_source=interpretation_source,
        pipeline_ms=elapsed_ms,
    )


def _interpretation_views(
    request: OptimizeRequest, directives: Sequence[DirectiveInterpretation]
) -> list[NoteInterpretationView]:
    views: list[NoteInterpretationView] = []
    for directive in sorted(directives, key=lambda item: item.note_index):
        note = (
            request.operator_notes[directive.note_index]
            if directive.note_index < len(request.operator_notes)
            else ""
        )
        adjustment = directive.structured_adjustment
        value, label = _numeric_of(directive)
        views.append(
            NoteInterpretationView(
                note_index=directive.note_index,
                note=note,
                directive_type=directive.directive_type,
                applies=directive.applies,
                hours=list(getattr(adjustment, "hours", []) or []),
                numeric_value=value,
                numeric_label=label,
                explanation=directive.explanation,
            )
        )
    return views


def _numeric_of(directive: DirectiveInterpretation) -> tuple[float | None, str]:
    adjustment = directive.structured_adjustment
    if adjustment is None:
        return None, ""
    for attribute, label in (
        ("factor", "remaining solar fraction"),
        ("minimum_energy_kwh", "reserve floor (kWh)"),
        ("max_grid_kwh", "grid cap (kWh/h)"),
    ):
        if hasattr(adjustment, attribute):
            return float(getattr(adjustment, attribute)), label
    return None, ""


def _hour_detail(index, hour_input, entry, compiled: CompiledConstraints) -> HourDetail:
    grid_cap = float(compiled.grid_upper[index])
    capped = grid_cap if grid_cap != float("inf") else None

    binding: list[str] = []
    if entry.solar_used_kwh >= compiled.effective_solar[index] - BINDING_TOLERANCE > 0:
        binding.append("solar fully used")
    if capped is not None and entry.grid_kwh >= capped - BINDING_TOLERANCE:
        binding.append("grid cap")
    if entry.battery_energy_after_kwh <= compiled.min_energy[index] + BINDING_TOLERANCE:
        binding.append("battery at reserve floor")
    if not compiled.charge_allowed[index]:
        binding.append("charging prohibited")
    if not compiled.discharge_allowed[index]:
        binding.append("discharging prohibited")

    return HourDetail(
        hour=entry.hour,
        demand_kwh=hour_input.demand_kwh,
        original_solar_kwh=float(compiled.original_solar[index]),
        effective_solar_kwh=float(compiled.effective_solar[index]),
        solar_used_kwh=entry.solar_used_kwh,
        grid_kwh=entry.grid_kwh,
        battery_action=entry.battery_action,
        battery_kwh=entry.battery_kwh,
        battery_energy_after_kwh=entry.battery_energy_after_kwh,
        tariff_bdt_per_kwh=hour_input.tariff_bdt_per_kwh,
        cost_bdt=entry.grid_kwh * hour_input.tariff_bdt_per_kwh,
        min_energy_kwh=float(compiled.min_energy[index]),
        grid_cap_kwh=capped,
        charge_allowed=bool(compiled.charge_allowed[index]),
        discharge_allowed=bool(compiled.discharge_allowed[index]),
        binding=binding,
    )


def _solver_diagnostics(outcome: SolveOutcome, settings: Settings) -> SolverDiagnostics:
    lp = outcome.lp
    milp = outcome.milp
    respected = True
    if lp is not None and lp.cost is not None and milp is not None and milp.cost is not None:
        respected = milp.cost + max(settings.internal_tolerance, abs(lp.cost) * 1e-9) >= lp.cost

    return SolverDiagnostics(
        lp_status=str(lp.status) if lp is not None else "",
        lp_objective=lp.cost if lp is not None else None,
        milp_status=str(milp.status) if milp is not None else "",
        milp_objective=milp.cost if milp is not None else None,
        milp_gap=milp.mip_gap if milp is not None else None,
        proven_optimal=outcome.proven_optimal,
        lp_duration_ms=lp.duration_ms if lp is not None else 0.0,
        milp_duration_ms=milp.duration_ms if milp is not None else 0.0,
        lower_bound_respected=respected,
    )


def build_cost_comparison(
    request: OptimizeRequest,
    compiled: CompiledConstraints,
    response: OptimizeResponse,
    settings: Settings,
) -> CostComparison:
    """Compare against a no-storage baseline — honestly.

    The battery idles, solar covers what it can, and the grid covers the rest. That baseline is
    **not always legal**: a grid cap can make it impossible. When it is, it is labelled infeasible
    rather than quietly reported as a saving against a plan nobody could have run.
    """
    hours = request.canonical_hours()
    baseline_cost = 0.0
    feasible = True
    note = ""

    for index, hour in enumerate(hours):
        solar_used = min(float(compiled.effective_solar[index]), hour.demand_kwh)
        grid = hour.demand_kwh - solar_used
        cap = float(compiled.grid_upper[index])
        if grid > cap + BINDING_TOLERANCE:
            feasible = False
            note = (
                f"a no-storage plan would need {grid:.1f} kWh at hour {hour.hour}, "
                f"above the cap of {cap:.1f}"
            )
            break
        baseline_cost += grid * hour.tariff_bdt_per_kwh

    if not feasible:
        return CostComparison(
            optimized_cost_bdt=response.total_cost_bdt,
            baseline_feasible=False,
            baseline_note=note,
        )

    savings = baseline_cost - response.total_cost_bdt
    return CostComparison(
        optimized_cost_bdt=response.total_cost_bdt,
        baseline_cost_bdt=baseline_cost,
        baseline_feasible=True,
        baseline_note="battery idle, solar first, grid for the remainder",
        savings_bdt=savings,
        savings_percent=(savings / baseline_cost * 100.0) if baseline_cost else None,
    )


def solve_for_demo(
    request: OptimizeRequest,
    directives: Sequence[DirectiveInterpretation],
    service,
    settings: Settings | None = None,
) -> tuple[OptimizeResponse, SolveOutcome, float]:
    """Run the production solve and response build, timed."""
    settings = settings or get_settings()
    started = time.perf_counter()
    outcome = hybrid_solve(request, directives, settings)
    response = service.solve_and_build(request, directives)
    return response, outcome, (time.perf_counter() - started) * 1000.0


def paraphrase_variant(
    directives: Sequence[DirectiveInterpretation], note: str
) -> ParaphraseVariant:
    """Flatten one interpretation into the paraphrase-lab row."""
    if not directives:
        return ParaphraseVariant(note=note, error="no interpretation returned")
    directive = directives[0]
    value, _ = _numeric_of(directive)
    return ParaphraseVariant(
        note=note,
        directive_type=directive.directive_type,
        hours=list(getattr(directive.structured_adjustment, "hours", []) or []),
        numeric_value=value,
    )


__all__ = [
    "BINDING_TOLERANCE",
    "build_analysis",
    "build_cost_comparison",
    "paraphrase_variant",
    "solve_for_demo",
]
