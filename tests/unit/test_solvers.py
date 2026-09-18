"""LP relaxation, MILP, and hybrid orchestration tests.

Three things are being established here:

* **Optimality** — the MILP reproduces every published optimal cost, so the optimization-quality
  ratio ``organizer_optimal / team_cost`` is 1.0 on all known data.
* **Invariants** — ``LP <= MILP``, residuals in tolerance, and no hour both charging and
  discharging. These guard the response builder that comes next.
* **Edge and failure handling** — degenerate batteries, zero caps, negative tariffs, and
  infeasibility. Each must produce the *right kind* of failure, because the three failure
  classes map to three different HTTP responses.
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from app.optimizer.compile_directives import compile_directives
from app.optimizer.hybrid_solve import (
    SolveStatus,
    hybrid_solve,
    screen_baseline_feasibility,
)
from app.optimizer.lp_relaxation import LpStatus, solve_lp_relaxation
from app.optimizer.milp_solver import MilpStatus, solve_milp
from app.optimizer.model import CHARGE, DISCHARGE, build_model
from app.schemas.directive import (
    MaxGridWindowDirective,
    MinimumBatteryReserveDirective,
    NoChargeWindowDirective,
    NoDischargeWindowDirective,
    SolarReductionDirective,
)
from app.schemas.request import OptimizeRequest
from app.schemas.response import OptimizeResponse

JUDGE_TOLERANCE = 0.01


def _parsed(case) -> tuple[OptimizeRequest, list]:
    request = OptimizeRequest.model_validate(case["input"])
    directives = OptimizeResponse.model_validate(case["expected_output"]).directive_interpretation
    return request, list(directives)


def _request_from(case, **battery_overrides) -> OptimizeRequest:
    body = copy.deepcopy(case["input"])
    body["battery"].update(battery_overrides)
    return OptimizeRequest.model_validate(body)


# ------------------------------------------------------------------ optimality on real data


def test_every_reference_case_reaches_the_published_optimum(public_cases, extended_cases):
    """The headline regression: 44 scenarios, ground-truth directives, exact optimal cost."""
    failures = []
    for case in [*public_cases, *extended_cases]:
        request, directives = _parsed(case)
        outcome = hybrid_solve(request, directives)

        published = case["expected_output"]["total_cost_bdt"]
        if not outcome.ok:
            failures.append(f"{case['id']}: {outcome.status} {outcome.detail}")
            continue
        if abs(outcome.cost - published) > JUDGE_TOLERANCE:
            failures.append(f"{case['id']}: solved {outcome.cost} vs published {published}")
        if not outcome.proven_optimal:
            failures.append(f"{case['id']}: MILP optimality was not proven")
    assert not failures, "\n".join(failures)


def test_lp_is_never_above_the_milp_on_any_reference_case(public_cases, extended_cases):
    for case in [*public_cases, *extended_cases]:
        request, directives = _parsed(case)
        outcome = hybrid_solve(request, directives)

        assert outcome.ok, case["id"]
        assert outcome.lp_lower_bound <= outcome.cost + 1e-6, case["id"]


def test_milp_never_charges_and_discharges_in_the_same_hour(public_cases, extended_cases):
    for case in [*public_cases, *extended_cases]:
        request, directives = _parsed(case)
        outcome = hybrid_solve(request, directives)

        charge = outcome.solution[CHARGE]
        discharge = outcome.solution[DISCHARGE]
        assert not ((charge > 1e-6) & (discharge > 1e-6)).any(), case["id"]


def test_solved_plans_respect_the_compiled_directive_bounds(public_cases, extended_cases):
    """Directives must bind the *solved* plan, not merely the published reference one."""
    for case in [*public_cases, *extended_cases]:
        request, directives = _parsed(case)
        outcome = hybrid_solve(request, directives)
        vectors = outcome.model.split(outcome.solution)
        compiled = outcome.compiled

        assert (vectors.solar_used <= compiled.effective_solar + 1e-6).all(), case["id"]
        assert (vectors.grid <= compiled.grid_upper + 1e-6).all(), case["id"]
        assert (vectors.energy >= compiled.min_energy - 1e-6).all(), case["id"]
        assert (vectors.charge[~compiled.charge_allowed] <= 1e-6).all(), case["id"]
        assert (vectors.discharge[~compiled.discharge_allowed] <= 1e-6).all(), case["id"]


# ----------------------------------------------------------------- baseline feasibility screen


def test_baseline_screen_passes_for_a_normal_scenario(public_cases):
    screen = screen_baseline_feasibility(OptimizeRequest.model_validate(public_cases[0]["input"]))

    assert screen.feasible
    assert screen.lp.is_optimal
    assert screen.lower_bound_cost > 0


def test_baseline_screen_ignores_operator_notes(public_cases):
    """No directives are applied, so the baseline bound is never above the constrained optimum."""
    case = next(
        c
        for c in public_cases
        if any(d["directive_type"] != "no_op" for d in c["expected_output"]["directive_interpretation"])
    )
    request, directives = _parsed(case)

    screen = screen_baseline_feasibility(request)
    constrained = hybrid_solve(request, directives)

    assert screen.lower_bound_cost <= constrained.cost + 1e-6


def test_initial_energy_below_the_reserve_floor_is_baseline_infeasible(public_cases):
    """End-of-day neutrality forces E[23] back to the initial level, which is below the floor.

    This is exactly the case the pre-LLM screen exists for: structurally valid, semantically
    impossible, and not the interpreter's fault.
    """
    case = public_cases[0]
    capacity = case["input"]["battery"]["capacity_kwh"]
    request = _request_from(case, initial_energy_kwh=10.0, minimum_energy_kwh=min(80.0, capacity))

    screen = screen_baseline_feasibility(request)

    assert not screen.feasible
    assert screen.lp.status is LpStatus.INFEASIBLE


def test_a_completely_rigid_battery_is_still_schedulable(public_cases):
    """A battery pinned full, with zero charge and discharge rates, is rigid but not impossible.

    The grid simply covers every hour. The screen must not reject a scenario for being
    inflexible — that would turn a valid hidden case into a 422.
    """
    case = public_cases[0]
    capacity = case["input"]["battery"]["capacity_kwh"]
    request = _request_from(
        case,
        initial_energy_kwh=capacity,
        minimum_energy_kwh=capacity,
        max_charge_kwh_per_hour=0.0,
        max_discharge_kwh_per_hour=0.0,
    )

    assert screen_baseline_feasibility(request).feasible


# ------------------------------------------------------------------- directive infeasibility


def test_a_zero_grid_cap_without_enough_solar_is_directive_infeasible(public_cases):
    """The scenario is fine; this reading of the notes is not. That distinction drives a reparse."""
    case = public_cases[0]
    request = OptimizeRequest.model_validate(case["input"])
    night_hour = next(
        entry.hour
        for entry in request.canonical_hours()
        if entry.solar_kwh == 0 and entry.demand_kwh > 0
    )

    assert screen_baseline_feasibility(request).feasible

    outcome = hybrid_solve(
        request,
        [MaxGridWindowDirective(note_index=0, structured_adjustment={"hours": [night_hour], "max_grid_kwh": 0.0})],
    )

    assert outcome.status is SolveStatus.DIRECTIVE_INFEASIBLE
    assert outcome.detail


def test_an_impossible_reserve_combination_is_directive_infeasible(public_cases):
    """A floor at full capacity for an hour the battery cannot reach in time."""
    case = public_cases[0]
    request = OptimizeRequest.model_validate(case["input"])
    capacity = request.battery.capacity_kwh

    outcome = hybrid_solve(
        request,
        [
            MinimumBatteryReserveDirective(
                note_index=0, structured_adjustment={"hours": [0], "minimum_energy_kwh": capacity}
            ),
            NoChargeWindowDirective(note_index=1, structured_adjustment={"hours": [0]}),
        ],
    )

    assert outcome.status is SolveStatus.DIRECTIVE_INFEASIBLE


# ------------------------------------------------------------------------------ edge cases


def test_zero_capacity_battery_is_schedulable(public_cases):
    """Allowed when relationally consistent: the battery simply never participates."""
    request = _request_from(
        public_cases[0],
        capacity_kwh=0.0,
        initial_energy_kwh=0.0,
        minimum_energy_kwh=0.0,
        max_charge_kwh_per_hour=0.0,
        max_discharge_kwh_per_hour=0.0,
    )
    outcome = hybrid_solve(request, [])

    assert outcome.ok
    vectors = outcome.model.split(outcome.solution)
    assert np.allclose(vectors.charge, 0.0)
    assert np.allclose(vectors.discharge, 0.0)
    assert np.allclose(vectors.energy, 0.0)


def test_zero_charge_rate_leaves_the_battery_idle(public_cases):
    """With no way to recharge, end-of-day neutrality forbids discharging at all."""
    request = _request_from(public_cases[0], max_charge_kwh_per_hour=0.0)
    outcome = hybrid_solve(request, [])

    assert outcome.ok
    vectors = outcome.model.split(outcome.solution)
    assert np.allclose(vectors.charge, 0.0, atol=1e-6)
    assert np.allclose(vectors.discharge, 0.0, atol=1e-6)


def test_negative_tariff_solves_without_error(public_cases):
    """Negative tariffs are not forbidden by the request schema, so they must not break the solver."""
    body = copy.deepcopy(public_cases[0]["input"])
    for entry in body["hours"]:
        entry["tariff_bdt_per_kwh"] = -2.0
    request = OptimizeRequest.model_validate(body)

    outcome = hybrid_solve(request, [])

    assert outcome.ok
    assert outcome.cost < 0  # being paid to import is cheapest, and the model is still bounded


def test_zero_solar_factor_forces_grid_and_battery_only(public_cases):
    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    sunny = [entry.hour for entry in request.canonical_hours() if entry.solar_kwh > 0][:3]

    outcome = hybrid_solve(
        request,
        [SolarReductionDirective(note_index=0, structured_adjustment={"hours": sunny, "factor": 0.0})],
    )

    assert outcome.ok
    vectors = outcome.model.split(outcome.solution)
    assert np.allclose(vectors.solar_used[sunny], 0.0, atol=1e-9)


def test_both_bans_on_one_hour_force_that_hour_idle(public_cases):
    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    outcome = hybrid_solve(
        request,
        [
            NoChargeWindowDirective(note_index=0, structured_adjustment={"hours": [15]}),
            NoDischargeWindowDirective(note_index=1, structured_adjustment={"hours": [15]}),
        ],
    )

    assert outcome.ok
    vectors = outcome.model.split(outcome.solution)
    assert vectors.charge[15] == pytest.approx(0.0, abs=1e-9)
    assert vectors.discharge[15] == pytest.approx(0.0, abs=1e-9)


def test_applying_real_directives_never_lowers_the_optimal_cost(public_cases, extended_cases):
    """Metamorphic sanity across every reference case: a smaller feasible set cannot be cheaper.

    The tightenings here are the organizers' own ground-truth directives, so each one is known
    to be feasible. (An arbitrary invented cap can make a scenario infeasible, in which case the
    property simply does not apply — see the directive-infeasibility tests above.)
    """
    for case in [*public_cases, *extended_cases]:
        request, directives = _parsed(case)
        if all(directive.directive_type == "no_op" for directive in directives):
            continue

        baseline = screen_baseline_feasibility(request)
        constrained = hybrid_solve(request, directives)

        assert baseline.feasible and constrained.ok, case["id"]
        assert constrained.cost >= baseline.lower_bound_cost - 1e-6, case["id"]


def test_a_binding_grid_cap_raises_or_holds_the_cost(public_cases):
    """A cap pinned to the unconstrained peak keeps the old plan feasible, so cost cannot drop."""
    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    unconstrained = hybrid_solve(request, [])
    peak = float(unconstrained.model.split(unconstrained.solution).grid.max())

    capped = hybrid_solve(
        request,
        [
            MaxGridWindowDirective(
                note_index=0,
                structured_adjustment={"hours": list(range(24)), "max_grid_kwh": peak},
            )
        ],
    )

    assert unconstrained.ok and capped.ok
    assert capped.cost >= unconstrained.cost - 1e-6
    assert capped.model.split(capped.solution).grid.max() <= peak + 1e-6


def test_more_solar_never_raises_the_optimal_cost(public_cases):
    """Reducing solar can only remove options, so the reduced plan cannot be cheaper."""
    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    full_solar = hybrid_solve(request, [])
    reduced = hybrid_solve(
        request,
        [
            SolarReductionDirective(
                note_index=0, structured_adjustment={"hours": list(range(8, 17)), "factor": 0.1}
            )
        ],
    )

    assert full_solar.ok and reduced.ok
    assert reduced.cost >= full_solar.cost - 1e-6


# -------------------------------------------------------------------- solver-level behaviour


def test_lp_and_milp_solve_the_same_model_object(public_cases):
    request, directives = _parsed(public_cases[0])
    model = build_model(request, compile_directives(request, directives))

    lp = solve_lp_relaxation(model)
    milp = solve_milp(model)

    assert lp.status is LpStatus.OPTIMAL
    assert milp.status is MilpStatus.OPTIMAL
    assert lp.cost <= milp.cost + 1e-6
    assert lp.duration_ms >= 0 and milp.duration_ms >= 0


def test_relaxation_allows_fractional_modes_that_the_milp_forbids(public_cases):
    """Confirms the relaxation is genuinely looser — otherwise the MILP stage proves nothing."""
    request, directives = _parsed(public_cases[0])
    model = build_model(request, compile_directives(request, directives))

    lp = solve_lp_relaxation(model)
    milp = solve_milp(model)

    assert set(np.unique(np.round(milp.solution[model.integrality == 1], 6))) <= {0.0, 1.0}
    assert lp.solution is not None


def test_solver_failures_surface_as_status_not_exception(public_cases, monkeypatch):
    """A broken solver must never escape as a traceback; the service maps statuses to responses."""
    import app.optimizer.lp_relaxation as lp_module

    def _explode(*_args, **_kwargs):
        raise RuntimeError("simulated solver crash")

    monkeypatch.setattr(lp_module, "linprog", _explode)
    request, directives = _parsed(public_cases[0])

    outcome = hybrid_solve(request, directives)

    assert outcome.status is SolveStatus.SOLVER_FAILURE
    assert outcome.lp.status is LpStatus.ERROR


def test_invariant_breach_is_reported_rather_than_returned(public_cases, monkeypatch):
    """If the MILP ever undercut the LP bound, the plan must not be used."""
    import app.optimizer.hybrid_solve as hybrid_module
    from app.optimizer.lp_relaxation import LpResult

    real_solver = hybrid_module.solve_lp_relaxation

    def _inflated(model, settings=None):
        result = real_solver(model, settings)
        return LpResult(
            status=result.status,
            cost=(result.cost or 0.0) + 10_000.0,
            solution=result.solution,
            duration_ms=result.duration_ms,
        )

    monkeypatch.setattr(hybrid_module, "solve_lp_relaxation", _inflated)
    request, directives = _parsed(public_cases[0])

    outcome = hybrid_solve(request, directives)

    assert outcome.status is SolveStatus.SOLVER_FAILURE
    assert any("below the LP lower bound" in detail for detail in outcome.detail)


def test_milp_solves_to_exact_optimality_not_a_near_optimal_gap(public_cases):
    """Regression: HiGHS defaults to a 1e-4 relative MIP gap and still reports success.

    Found by the metamorphic suite — adding a constraint appeared to *lower* the optimal cost,
    which is impossible for nested feasible sets. The real cause was the solver stopping at a
    provably near-optimal solution while `status=0` made it look proven optimal. Optimization
    credit is `min(1, optimal/team_cost)`, so an unnecessary 0.01% gap is an unnecessary score
    loss, and `proven_optimal` would have been a false claim.

    The LP relaxation is the true lower bound here, so an exactly-solved MILP must match it.
    """
    from app.optimizer.lp_relaxation import solve_lp_relaxation

    for case in public_cases:
        request, directives = _parsed(case)
        model = build_model(request, compile_directives(request, directives))

        lp = solve_lp_relaxation(model)
        milp_result = solve_milp(model)

        assert milp_result.status is MilpStatus.OPTIMAL, case["id"]
        assert milp_result.mip_gap == pytest.approx(0.0, abs=1e-12), case["id"]
        # Any residual gap would show up as the MILP sitting above its own lower bound.
        assert milp_result.cost == pytest.approx(lp.cost, abs=1e-6), case["id"]
