"""Response-building and canonicalization tests.

The failure this guards against is subtle and expensive: a solver vector that is perfectly
valid becomes an *invalid response* once each field is rounded on its own, because the energy
balance and the battery state stop agreeing. Every case here is about that boundary.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from app.api.errors import SolverFailure
from app.optimizer.hybrid_solve import hybrid_solve
from app.optimizer.model import CHARGE, DISCHARGE, SOLAR
from app.optimizer.result import build_hourly_plan
from app.schemas.directive import NoChargeWindowDirective, NoOpDirective
from app.schemas.request import OptimizeRequest
from app.schemas.response import OptimizeResponse
from app.validation.replay import replay
from app.validation.totals import recalculate_totals


def _solved(case, directives=None):
    request = OptimizeRequest.model_validate(case["input"])
    if directives is None:
        directives = list(
            OptimizeResponse.model_validate(case["expected_output"]).directive_interpretation
        )
    return request, directives, hybrid_solve(request, directives)


def _as_response(request, directives, plan) -> OptimizeResponse:
    tariffs = {entry.hour: entry.tariff_bdt_per_kwh for entry in request.canonical_hours()}
    totals = recalculate_totals(plan, tariffs)
    return OptimizeResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=list(directives),
        hourly_plan=plan,
        total_grid_kwh=totals.total_grid_kwh,
        total_cost_bdt=totals.total_cost_bdt,
        peak_grid_kwh=totals.peak_grid_kwh,
        plan_summary="summary",
    )


# ------------------------------------------------------------------- plan construction


def test_plan_has_24_canonically_ordered_hours(public_cases):
    request, directives, outcome = _solved(public_cases[0])
    plan = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=6)

    assert [entry.hour for entry in plan] == list(range(24))


def test_idle_hours_carry_an_exact_zero(public_cases):
    """Not "close to zero" — the contract says battery_kwh must be 0 when idle."""
    request, directives, outcome = _solved(public_cases[0])
    plan = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=6)

    idle = [entry for entry in plan if entry.battery_action == "idle"]
    assert idle, "the sample plan should contain at least one idle hour"
    assert all(entry.battery_kwh == 0.0 for entry in idle)


def test_action_is_derived_from_the_magnitude_not_the_mode_variable(public_cases):
    """A mode flag set with a zero amount is an idle hour, not a charge of 0."""
    from app.optimizer.model import CHARGE_MODE

    request, directives, outcome = _solved(public_cases[0])
    solution = outcome.solution.copy()
    idle_hour = next(
        hour
        for hour in range(24)
        if solution[CHARGE][hour] < 1e-9 and solution[DISCHARGE][hour] < 1e-9
    )
    solution[CHARGE_MODE.start + idle_hour] = 1.0  # mode on, amount still zero

    plan = build_hourly_plan(request, outcome.compiled, solution, decimals=6)

    assert plan[idle_hour].battery_action == "idle"
    assert plan[idle_hour].battery_kwh == 0.0


def test_an_unrepresentable_schedule_fails_closed(public_cases):
    """A reconstruction that drives the battery negative must be a classified failure."""
    request, directives, outcome = _solved(public_cases[0])
    solution = outcome.solution.copy()
    charging_hour = next(hour for hour in range(24) if solution[CHARGE][hour] > 1e-6)
    solution[CHARGE.start + charging_hour] = 0.0  # remove a charge, keep every discharge

    with pytest.raises(SolverFailure, match="not representable"):
        build_hourly_plan(request, outcome.compiled, solution, decimals=6)


def test_state_is_rebuilt_sequentially_rather_than_read_from_the_solver(public_cases):
    """Corrupting the solver's state vector must not affect the response."""
    request, directives, outcome = _solved(public_cases[0])
    corrupted = outcome.solution.copy()
    corrupted[4 * 24 : 5 * 24] += 37.0  # the ENERGY block

    from_clean = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=6)
    from_corrupted = build_hourly_plan(request, outcome.compiled, corrupted, decimals=6)

    assert [entry.battery_energy_after_kwh for entry in from_clean] == [
        entry.battery_energy_after_kwh for entry in from_corrupted
    ]


def test_grid_is_recomputed_from_the_energy_balance(public_cases):
    """Corrupting the solver's grid vector must not affect the response either."""
    request, directives, outcome = _solved(public_cases[0])
    corrupted = outcome.solution.copy()
    corrupted[0:24] += 13.0  # the GRID block

    from_clean = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=6)
    from_corrupted = build_hourly_plan(request, outcome.compiled, corrupted, decimals=6)

    assert [entry.grid_kwh for entry in from_clean] == [entry.grid_kwh for entry in from_corrupted]


def test_tiny_solver_dust_is_canonicalized_away(public_cases):
    request, directives, outcome = _solved(public_cases[0])
    dusty = outcome.solution.copy()
    idle_hour = next(
        hour
        for hour in range(24)
        if dusty[CHARGE][hour] < 1e-9 and dusty[DISCHARGE][hour] < 1e-9
    )
    dusty[CHARGE.start + idle_hour] = 1e-13
    dusty[DISCHARGE.start + idle_hour] = -1e-13

    plan = build_hourly_plan(request, outcome.compiled, dusty, decimals=6)

    assert plan[idle_hour].battery_action == "idle"
    assert plan[idle_hour].battery_kwh == 0.0


# --------------------------------------------------------------- fail closed, never clip


def test_material_overshoot_fails_closed(public_cases):
    """Rounding artifacts get clipped; a real violation must not be clipped into validity."""
    request, directives, outcome = _solved(public_cases[0])
    broken = outcome.solution.copy()
    broken[CHARGE.start + 5] = request.battery.max_charge_kwh_per_hour + 10.0

    with pytest.raises(SolverFailure, match="exceeds its limit"):
        build_hourly_plan(request, outcome.compiled, broken, decimals=6)


def test_material_negative_value_fails_closed(public_cases):
    request, directives, outcome = _solved(public_cases[0])
    broken = outcome.solution.copy()
    broken[SOLAR.start + 10] = -5.0

    with pytest.raises(SolverFailure, match="negative"):
        build_hourly_plan(request, outcome.compiled, broken, decimals=6)


def test_activity_in_a_banned_hour_fails_closed(public_cases):
    """Silently zeroing it would produce a valid-looking plan that hides a solver fault."""
    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    directives = [NoChargeWindowDirective(note_index=0, structured_adjustment={"hours": [3]})]
    outcome = hybrid_solve(request, directives)

    broken = outcome.solution.copy()
    broken[CHARGE.start + 3] = 10.0

    with pytest.raises(SolverFailure, match="prohibited"):
        build_hourly_plan(request, outcome.compiled, broken, decimals=6)


def test_simultaneous_charge_and_discharge_fails_closed(public_cases):
    request, directives, outcome = _solved(public_cases[0])
    broken = outcome.solution.copy()
    broken[CHARGE.start + 6] = 10.0
    broken[DISCHARGE.start + 6] = 10.0

    with pytest.raises(SolverFailure, match="same hour"):
        build_hourly_plan(request, outcome.compiled, broken, decimals=6)


# ------------------------------------------------------------------ numerical integrity


def test_rounded_plans_replay_clean_on_every_reference_case(public_cases, extended_cases):
    failures = []
    for case in [*public_cases, *extended_cases]:
        request, directives, outcome = _solved(case)
        plan = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=6)
        report = replay(request, directives, _as_response(request, directives, plan))
        if not report.ok:
            failures.append(f"{case['id']}: {report.messages}")
    assert not failures, "\n".join(failures)


def test_rounding_alone_can_break_a_plan_which_is_why_the_ladder_exists(public_cases):
    """Documents the failure mode: awkward decimals defeat coarse rounding, full precision holds.

    This is the exact bug the guide warns about — a valid solver vector turned invalid by
    independent rounding — and it is caught here by the independent replay validator.
    """
    body = copy.deepcopy(public_cases[0]["input"])
    for entry in body["hours"]:
        entry["demand_kwh"] += 0.123456789
        if entry["solar_kwh"]:
            entry["solar_kwh"] += 0.987654321
    request = OptimizeRequest.model_validate(body)
    directives = list(
        OptimizeResponse.model_validate(public_cases[0]["expected_output"]).directive_interpretation
    )
    outcome = hybrid_solve(request, directives)

    coarse = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=6)
    exact = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=None)

    coarse_report = replay(request, directives, _as_response(request, directives, coarse))
    exact_report = replay(request, directives, _as_response(request, directives, exact))

    assert not coarse_report.ok, "the coarse rounding should be the one that drifts"
    assert exact_report.ok, "full precision must survive"


def test_totals_are_recomputed_from_the_returned_plan(public_cases):
    request, directives, outcome = _solved(public_cases[0])
    plan = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=6)
    response = _as_response(request, directives, plan)

    assert response.total_grid_kwh == pytest.approx(sum(entry.grid_kwh for entry in plan))
    assert response.peak_grid_kwh == pytest.approx(max(entry.grid_kwh for entry in plan))
    tariffs = {entry.hour: entry.tariff_bdt_per_kwh for entry in request.canonical_hours()}
    expected_cost = sum(entry.grid_kwh * tariffs[entry.hour] for entry in plan)
    assert response.total_cost_bdt == pytest.approx(expected_cost)


def test_no_simultaneous_charge_and_discharge_in_any_built_plan(public_cases, extended_cases):
    for case in [*public_cases, *extended_cases]:
        request, directives, outcome = _solved(case)
        plan = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=6)

        assert all(
            (entry.battery_action == "idle") == (entry.battery_kwh == 0.0)
            or entry.battery_action in ("charge", "discharge")
            for entry in plan
        ), case["id"]
        assert all(entry.battery_kwh >= 0.0 for entry in plan), case["id"]


def test_zero_capacity_battery_produces_an_all_idle_plan(public_cases):
    body = copy.deepcopy(public_cases[0]["input"])
    body["battery"].update(
        capacity_kwh=0.0,
        initial_energy_kwh=0.0,
        minimum_energy_kwh=0.0,
        max_charge_kwh_per_hour=0.0,
        max_discharge_kwh_per_hour=0.0,
    )
    request = OptimizeRequest.model_validate(body)
    # One interpretation entry per operator note, or replay rightly objects to the mismatch.
    directives = [NoOpDirective(note_index=index) for index in range(len(request.operator_notes))]
    outcome = hybrid_solve(request, directives)
    plan = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=6)

    assert all(entry.battery_action == "idle" for entry in plan)
    assert all(entry.battery_energy_after_kwh == 0.0 for entry in plan)
    assert replay(request, directives, _as_response(request, directives, plan)).ok


def test_zero_solar_factor_yields_zero_solar_use(public_cases):
    from app.schemas.directive import SolarReductionDirective

    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    sunny = [entry.hour for entry in request.canonical_hours() if entry.solar_kwh > 0][:3]
    directives = [
        SolarReductionDirective(note_index=0, structured_adjustment={"hours": sunny, "factor": 0.0}),
        *(
            NoOpDirective(note_index=index)
            for index in range(1, len(request.operator_notes))
        ),
    ]
    outcome = hybrid_solve(request, directives)
    plan = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=6)

    assert all(plan[hour].solar_used_kwh == 0.0 for hour in sunny)
    assert replay(request, directives, _as_response(request, directives, plan)).ok


def test_serialized_and_reparsed_plan_is_identical(public_cases):
    """The wire representation must reconstruct the same numbers it was built from."""
    request, directives, outcome = _solved(public_cases[0])
    plan = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=6)
    response = _as_response(request, directives, plan)

    reparsed = OptimizeResponse.model_validate_json(response.model_dump_json())

    assert reparsed.model_dump() == response.model_dump()
    assert np.allclose(
        [entry.grid_kwh for entry in reparsed.hourly_plan],
        [entry.grid_kwh for entry in plan],
        atol=0.0,
    )
