"""Property and metamorphic tests over randomly generated scenarios.

The reference packs prove the pipeline on 44 scenarios somebody wrote down. Hidden cases will
vary demand, solar, tariff, battery state, rate limits and directive combinations in ways nobody
here anticipated, and those are exactly the inputs that expose an integration bug between the
compiler, the model builder and the response builder.

Two kinds of check:

* **Properties** — invariants that must hold for *every* solved scenario: energy balance,
  battery bounds and transitions, rate limits, end-of-day neutrality, directive compliance,
  ``LP <= MILP``, and recalculated totals.
* **Metamorphic relations** — how the optimum must *move* when an input changes. These are the
  valuable ones, because they need no known answer: more solar cannot cost more, tightening a
  feasible constraint cannot cost less.

Generation is seeded, so a failure is reproducible from the printed seed rather than being a
one-off that vanishes on rerun. ``random.Random`` is used instead of adding a dependency.
"""

from __future__ import annotations

import random

import pytest

from app.optimizer.compile_directives import compile_directives
from app.optimizer.hybrid_solve import SolveStatus, hybrid_solve, screen_baseline_feasibility
from app.optimizer.result import build_hourly_plan
from app.schemas.directive import (
    MaxGridWindowDirective,
    MinimumBatteryReserveDirective,
    NoChargeWindowDirective,
    NoDischargeWindowDirective,
    NoOpDirective,
    SolarReductionDirective,
)
from app.schemas.request import OptimizeRequest
from app.schemas.response import OptimizeResponse
from app.validation.replay import replay
from app.validation.totals import recalculate_totals

SCENARIO_COUNT = 40
TOLERANCE = 1e-6


def _scenario(seed: int) -> OptimizeRequest:
    """A random but *schedulable* scenario.

    Battery values are derived from capacity rather than drawn independently, because an
    independently random battery is usually infeasible and would make the suite mostly test the
    generator rather than the optimizer.
    """
    rng = random.Random(seed)

    capacity = rng.choice([0.0, 50.0, 120.0, 200.0, 400.0])
    initial = round(rng.uniform(0.0, capacity), 2)
    minimum = round(rng.uniform(0.0, initial), 2) if capacity else 0.0
    max_charge = rng.choice([0.0, 10.0, 40.0, 75.0])
    max_discharge = rng.choice([0.0, 10.0, 40.0, 75.0])

    hours = []
    for hour in range(24):
        daylight = 7 <= hour <= 17
        hours.append(
            {
                "hour": hour,
                "demand_kwh": round(rng.uniform(0.0, 260.0), 3),
                "solar_kwh": round(rng.uniform(0.0, 180.0), 3) if daylight else 0.0,
                # Tariffs may be negative: the request schema never forbids it.
                "tariff_bdt_per_kwh": round(rng.uniform(-2.0, 22.0), 3),
            }
        )

    return OptimizeRequest.model_validate(
        {
            "scenario_id": f"PROP-{seed}",
            "operator_notes": ["generated scenario"],
            "hours": hours,
            "battery": {
                "capacity_kwh": capacity,
                "initial_energy_kwh": initial,
                "minimum_energy_kwh": minimum,
                "max_charge_kwh_per_hour": max_charge,
                "max_discharge_kwh_per_hour": max_discharge,
            },
        }
    )


def _directives(seed: int, request: OptimizeRequest):
    """A random, individually valid directive set for this scenario."""
    rng = random.Random(seed * 7919)
    capacity = request.battery.capacity_kwh
    choice = rng.randrange(6)

    hours = sorted(rng.sample(range(24), rng.randint(1, 4)))
    if choice == 0:
        return [SolarReductionDirective(note_index=0, structured_adjustment={"hours": hours, "factor": rng.choice([0.0, 0.2, 0.5, 0.8, 1.0])})]
    if choice == 1 and capacity > 0:
        floor = round(rng.uniform(0.0, capacity), 2)
        return [MinimumBatteryReserveDirective(note_index=0, structured_adjustment={"hours": hours, "minimum_energy_kwh": floor})]
    if choice == 2:
        return [NoChargeWindowDirective(note_index=0, structured_adjustment={"hours": hours})]
    if choice == 3:
        return [NoDischargeWindowDirective(note_index=0, structured_adjustment={"hours": hours})]
    if choice == 4:
        cap = round(rng.uniform(0.0, 400.0), 2)
        return [MaxGridWindowDirective(note_index=0, structured_adjustment={"hours": hours, "max_grid_kwh": cap})]
    return [NoOpDirective(note_index=0)]


def _solved_response(request: OptimizeRequest, directives) -> OptimizeResponse | None:
    outcome = hybrid_solve(request, directives)
    if not outcome.ok:
        return None
    plan = build_hourly_plan(request, outcome.compiled, outcome.solution, decimals=6)
    tariffs = {entry.hour: entry.tariff_bdt_per_kwh for entry in request.canonical_hours()}
    totals = recalculate_totals(plan, tariffs)
    return OptimizeResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=list(directives),
        hourly_plan=plan,
        total_grid_kwh=totals.total_grid_kwh,
        total_cost_bdt=totals.total_cost_bdt,
        peak_grid_kwh=totals.peak_grid_kwh,
        plan_summary="generated",
    )


# ------------------------------------------------------------------------- properties


def test_every_solvable_random_scenario_produces_a_replayable_plan():
    """The core invariant sweep: balance, bounds, transitions, neutrality, totals."""
    failures = []
    solved = 0

    for seed in range(SCENARIO_COUNT):
        request = _scenario(seed)
        directives = _directives(seed, request)
        if not screen_baseline_feasibility(request).feasible:
            continue

        outcome = hybrid_solve(request, directives)
        if outcome.status is SolveStatus.DIRECTIVE_INFEASIBLE:
            continue  # a randomly generated directive may genuinely be impossible
        if not outcome.ok:
            failures.append(f"seed {seed}: {outcome.status} {outcome.detail}")
            continue

        response = _solved_response(request, directives)
        report = replay(request, directives, response)
        if not report.ok:
            failures.append(f"seed {seed}: replay {report.messages}")
        solved += 1

    assert not failures, "\n".join(failures)
    assert solved >= 10, f"only {solved} scenarios were solvable; the generator is too hostile"


def test_no_random_solution_charges_and_discharges_in_the_same_hour():
    for seed in range(SCENARIO_COUNT):
        request = _scenario(seed)
        if not screen_baseline_feasibility(request).feasible:
            continue
        outcome = hybrid_solve(request, [NoOpDirective(note_index=0)])
        if not outcome.ok:
            continue

        vectors = outcome.model.split(outcome.solution)
        both = (vectors.charge > TOLERANCE) & (vectors.discharge > TOLERANCE)
        assert not both.any(), f"seed {seed} charges and discharges in the same hour"


def test_lp_is_always_a_lower_bound_on_the_milp():
    for seed in range(SCENARIO_COUNT):
        request = _scenario(seed)
        directives = _directives(seed, request)
        outcome = hybrid_solve(request, directives)
        if not outcome.ok:
            continue

        assert outcome.lp_lower_bound <= outcome.cost + TOLERANCE, f"seed {seed}"


def test_solved_plans_never_exceed_their_compiled_bounds():
    for seed in range(SCENARIO_COUNT):
        request = _scenario(seed)
        directives = _directives(seed, request)
        outcome = hybrid_solve(request, directives)
        if not outcome.ok:
            continue

        compiled = compile_directives(request, directives)
        vectors = outcome.model.split(outcome.solution)

        assert (vectors.solar_used <= compiled.effective_solar + TOLERANCE).all(), f"seed {seed}"
        assert (vectors.grid <= compiled.grid_upper + TOLERANCE).all(), f"seed {seed}"
        assert (vectors.energy >= compiled.min_energy - TOLERANCE).all(), f"seed {seed}"
        assert (vectors.energy <= request.battery.capacity_kwh + TOLERANCE).all(), f"seed {seed}"
        assert (vectors.charge <= request.battery.max_charge_kwh_per_hour + TOLERANCE).all(), f"seed {seed}"
        assert (
            vectors.discharge <= request.battery.max_discharge_kwh_per_hour + TOLERANCE
        ).all(), f"seed {seed}"


def test_solving_is_deterministic():
    """Same input, same plan — otherwise a cache or a retry could return a different answer."""
    for seed in range(10):
        request = _scenario(seed)
        directives = _directives(seed, request)
        first = hybrid_solve(request, directives)
        second = hybrid_solve(request, directives)

        if not first.ok:
            assert first.status is second.status, f"seed {seed}"
            continue
        assert first.cost == pytest.approx(second.cost, abs=1e-9), f"seed {seed}"


# ---------------------------------------------------------------- metamorphic relations


def _feasible_seeds(limit: int = SCENARIO_COUNT) -> list[int]:
    seeds = []
    for seed in range(limit):
        request = _scenario(seed)
        if screen_baseline_feasibility(request).feasible:
            seeds.append(seed)
    return seeds


def test_more_solar_can_never_cost_more():
    """Extra solar only adds options; the optimizer may ignore it, so cost cannot rise."""
    checked = 0
    for seed in _feasible_seeds():
        request = _scenario(seed)
        base = hybrid_solve(request, [NoOpDirective(note_index=0)])
        if not base.ok:
            continue

        richer_body = request.model_dump()
        for entry in richer_body["hours"]:
            entry["solar_kwh"] = entry["solar_kwh"] + 25.0
        richer = hybrid_solve(
            OptimizeRequest.model_validate(richer_body), [NoOpDirective(note_index=0)]
        )
        if not richer.ok:
            continue

        assert richer.cost <= base.cost + TOLERANCE, f"seed {seed}: more solar cost more"
        checked += 1

    assert checked >= 5


def test_reducing_solar_can_never_cost_less():
    """The mirror relation, expressed through a real directive rather than by editing inputs."""
    checked = 0
    for seed in _feasible_seeds():
        request = _scenario(seed)
        base = hybrid_solve(request, [NoOpDirective(note_index=0)])
        reduced = hybrid_solve(
            request,
            [
                SolarReductionDirective(
                    note_index=0, structured_adjustment={"hours": list(range(8, 17)), "factor": 0.1}
                )
            ],
        )
        if not (base.ok and reduced.ok):
            continue

        assert reduced.cost >= base.cost - TOLERANCE, f"seed {seed}"
        checked += 1

    assert checked >= 5


def test_tightening_a_grid_cap_can_never_cost_less():
    checked = 0
    for seed in _feasible_seeds():
        request = _scenario(seed)
        base = hybrid_solve(request, [NoOpDirective(note_index=0)])
        if not base.ok:
            continue

        # Pinned to the unconstrained peak, so the previous plan stays feasible by construction.
        peak = float(base.model.split(base.solution).grid.max())
        capped = hybrid_solve(
            request,
            [
                MaxGridWindowDirective(
                    note_index=0, structured_adjustment={"hours": list(range(24)), "max_grid_kwh": peak}
                )
            ],
        )
        if not capped.ok:
            continue

        assert capped.cost >= base.cost - TOLERANCE, f"seed {seed}"
        checked += 1

    assert checked >= 5


def test_raising_a_reserve_floor_can_never_cost_less():
    checked = 0
    for seed in _feasible_seeds():
        request = _scenario(seed)
        if request.battery.capacity_kwh <= 0:
            continue
        base = hybrid_solve(request, [NoOpDirective(note_index=0)])
        if not base.ok:
            continue

        # A floor the unconstrained plan already satisfies: feasible, and never cheaper.
        floor = float(base.model.split(base.solution).energy[18:22].min())
        raised = hybrid_solve(
            request,
            [
                MinimumBatteryReserveDirective(
                    note_index=0,
                    structured_adjustment={"hours": [18, 19, 20, 21], "minimum_energy_kwh": floor},
                )
            ],
        )
        if not raised.ok:
            continue

        assert raised.cost >= base.cost - TOLERANCE, f"seed {seed}"
        checked += 1

    assert checked >= 5


def test_removing_a_constraint_can_never_cost_more():
    """Dropping a ban widens the feasible set, so the optimum cannot get worse."""
    checked = 0
    for seed in _feasible_seeds():
        request = _scenario(seed)
        constrained = hybrid_solve(
            request,
            [NoChargeWindowDirective(note_index=0, structured_adjustment={"hours": [10, 11, 12]})],
        )
        free = hybrid_solve(request, [NoOpDirective(note_index=0)])
        if not (constrained.ok and free.ok):
            continue

        assert free.cost <= constrained.cost + TOLERANCE, f"seed {seed}"
        checked += 1

    assert checked >= 5


def test_a_no_op_directive_changes_nothing():
    for seed in _feasible_seeds(15):
        request = _scenario(seed)
        without = hybrid_solve(request, [])
        with_no_op = hybrid_solve(request, [NoOpDirective(note_index=0)])
        if not (without.ok and with_no_op.ok):
            continue

        assert without.cost == pytest.approx(with_no_op.cost, abs=1e-9), f"seed {seed}"


def test_hour_ordering_in_the_request_does_not_change_the_answer():
    """Array position is never the hour number; a shuffled request must solve identically."""
    for seed in _feasible_seeds(15):
        request = _scenario(seed)
        shuffled_body = request.model_dump()
        random.Random(seed).shuffle(shuffled_body["hours"])
        shuffled = OptimizeRequest.model_validate(shuffled_body)

        original = hybrid_solve(request, [NoOpDirective(note_index=0)])
        reordered = hybrid_solve(shuffled, [NoOpDirective(note_index=0)])
        if not (original.ok and reordered.ok):
            continue

        assert original.cost == pytest.approx(reordered.cost, abs=1e-9), f"seed {seed}"


# ------------------------------------------------------------------------ edge values


@pytest.mark.parametrize(
    ("capacity", "initial", "minimum", "charge_rate", "discharge_rate"),
    [
        (0.0, 0.0, 0.0, 0.0, 0.0),      # no battery at all
        (100.0, 100.0, 100.0, 50.0, 50.0),  # pinned full
        (100.0, 0.0, 0.0, 50.0, 50.0),      # starts empty
        (100.0, 50.0, 0.0, 0.0, 50.0),      # can discharge but never recharge
        (100.0, 50.0, 0.0, 50.0, 0.0),      # can charge but never discharge
    ],
    ids=["no-battery", "pinned-full", "starts-empty", "no-charging", "no-discharging"],
)
def test_degenerate_batteries_still_produce_valid_plans(
    capacity, initial, minimum, charge_rate, discharge_rate
):
    body = _scenario(1).model_dump()
    body["battery"] = {
        "capacity_kwh": capacity,
        "initial_energy_kwh": initial,
        "minimum_energy_kwh": minimum,
        "max_charge_kwh_per_hour": charge_rate,
        "max_discharge_kwh_per_hour": discharge_rate,
    }
    request = OptimizeRequest.model_validate(body)
    directives = [NoOpDirective(note_index=0)]

    assert screen_baseline_feasibility(request).feasible
    response = _solved_response(request, directives)

    assert response is not None
    assert replay(request, directives, response).ok


def test_zero_demand_and_zero_solar_is_handled():
    body = _scenario(3).model_dump()
    for entry in body["hours"]:
        entry["demand_kwh"] = 0.0
        entry["solar_kwh"] = 0.0
    request = OptimizeRequest.model_validate(body)
    directives = [NoOpDirective(note_index=0)]

    response = _solved_response(request, directives)

    assert response is not None
    assert response.total_grid_kwh == pytest.approx(0.0, abs=TOLERANCE)
    assert replay(request, directives, response).ok
