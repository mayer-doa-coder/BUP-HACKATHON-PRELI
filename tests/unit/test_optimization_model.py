"""Shared LP/MILP model tests.

The strongest available check is that every published reference schedule is a *feasible point*
of the model as built, and costs exactly what the organizers say it costs. That exercises the
objective, both equality blocks, all three inequality blocks, and every bound at once — against
data nobody on this team produced.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.optimizer.compile_directives import compile_directives
from app.optimizer.model import (
    CHARGE,
    CHARGE_MODE,
    DISCHARGE,
    DISCHARGE_MODE,
    ENERGY,
    EQUALITY_ROWS,
    GRID,
    INEQUALITY_ROWS,
    SOLAR,
    VARIABLE_COUNT,
    build_model,
    charge_index,
    charge_mode_index,
    discharge_index,
    discharge_mode_index,
    energy_index,
    grid_index,
    solar_index,
)
from app.schemas.directive import (
    MaxGridWindowDirective,
    MinimumBatteryReserveDirective,
    NoChargeWindowDirective,
    NoDischargeWindowDirective,
    SolarReductionDirective,
)
from app.schemas.request import OptimizeRequest
from app.schemas.response import OptimizeResponse

FEASIBILITY_TOLERANCE = 1e-9


def _model_for(case):
    request = OptimizeRequest.model_validate(case["input"])
    directives = OptimizeResponse.model_validate(case["expected_output"]).directive_interpretation
    compiled = compile_directives(request, directives)
    return request, build_model(request, compiled)


def _vector_from_plan(response: OptimizeResponse) -> np.ndarray:
    """Turn a published schedule into a point in the model's variable space."""
    vector = np.zeros(VARIABLE_COUNT, dtype=float)
    for entry in response.hourly_plan:
        hour = entry.hour
        vector[grid_index(hour)] = entry.grid_kwh
        vector[solar_index(hour)] = entry.solar_used_kwh
        vector[energy_index(hour)] = entry.battery_energy_after_kwh
        if entry.battery_action == "charge":
            vector[charge_index(hour)] = entry.battery_kwh
            vector[charge_mode_index(hour)] = 1.0
        elif entry.battery_action == "discharge":
            vector[discharge_index(hour)] = entry.battery_kwh
            vector[discharge_mode_index(hour)] = 1.0
    return vector


# ------------------------------------------------------------------- layout integrity


def test_variable_layout_is_the_expected_shape():
    assert VARIABLE_COUNT == 168
    assert EQUALITY_ROWS == 49  # 24 balance + 24 transition + 1 neutrality
    assert INEQUALITY_ROWS == 72  # 24 charge link + 24 discharge link + 24 exclusivity


def test_variable_blocks_do_not_overlap():
    blocks = [GRID, SOLAR, CHARGE, DISCHARGE, ENERGY, CHARGE_MODE, DISCHARGE_MODE]
    covered = [index for block in blocks for index in range(block.start, block.stop)]

    assert sorted(covered) == list(range(VARIABLE_COUNT))
    assert len(set(covered)) == VARIABLE_COUNT


def test_index_helpers_agree_with_the_slices():
    for hour in range(24):
        assert GRID.start <= grid_index(hour) < GRID.stop
        assert SOLAR.start <= solar_index(hour) < SOLAR.stop
        assert CHARGE.start <= charge_index(hour) < CHARGE.stop
        assert DISCHARGE.start <= discharge_index(hour) < DISCHARGE.stop
        assert ENERGY.start <= energy_index(hour) < ENERGY.stop
        assert CHARGE_MODE.start <= charge_mode_index(hour) < CHARGE_MODE.stop
        assert DISCHARGE_MODE.start <= discharge_mode_index(hour) < DISCHARGE_MODE.stop


def test_model_shapes(public_cases):
    _, model = _model_for(public_cases[0])

    assert model.objective.shape == (VARIABLE_COUNT,)
    assert model.a_eq.shape == (EQUALITY_ROWS, VARIABLE_COUNT)
    assert model.b_eq.shape == (EQUALITY_ROWS,)
    assert model.a_ub.shape == (INEQUALITY_ROWS, VARIABLE_COUNT)
    assert model.b_ub.shape == (INEQUALITY_ROWS,)
    assert model.lower_bounds.shape == (VARIABLE_COUNT,)
    assert model.upper_bounds.shape == (VARIABLE_COUNT,)
    assert len(model.scipy_bounds()) == VARIABLE_COUNT


# ------------------------------------------- reference schedules are feasible and priced right


def test_every_reference_schedule_is_a_feasible_point(public_cases, extended_cases):
    failures = []
    for case in [*public_cases, *extended_cases]:
        request, model = _model_for(case)
        response = OptimizeResponse.model_validate(case["expected_output"])
        vector = _vector_from_plan(response)

        equality_error, inequality_error, bound_error = model.residuals(vector)
        if max(equality_error, inequality_error, bound_error) > FEASIBILITY_TOLERANCE:
            failures.append(
                f"{case['id']}: eq={equality_error:.3g} ub={inequality_error:.3g} bound={bound_error:.3g}"
            )
    assert not failures, "\n".join(failures)


def test_objective_reproduces_the_published_cost(public_cases, extended_cases):
    failures = []
    for case in [*public_cases, *extended_cases]:
        _, model = _model_for(case)
        response = OptimizeResponse.model_validate(case["expected_output"])

        cost = model.cost_of(_vector_from_plan(response))
        if abs(cost - response.total_cost_bdt) > 1e-6:
            failures.append(f"{case['id']}: model cost {cost} != published {response.total_cost_bdt}")
    assert not failures, "\n".join(failures)


def test_residuals_actually_detect_an_infeasible_point(public_cases):
    """A check that never fails proves nothing, so confirm it reacts to a broken plan."""
    request, model = _model_for(public_cases[0])
    response = OptimizeResponse.model_validate(public_cases[0]["expected_output"])

    broken = _vector_from_plan(response)
    broken[grid_index(7)] += 5.0  # breaks the hour-7 energy balance
    equality_error, _, _ = model.residuals(broken)
    assert equality_error == pytest.approx(5.0)

    over_bound = _vector_from_plan(response)
    over_bound[energy_index(4)] = request.battery.capacity_kwh + 12.0
    _, _, bound_error = model.residuals(over_bound)
    assert bound_error == pytest.approx(12.0)


# --------------------------------------------------- directives arrive purely as bounds


def test_solar_reduction_lowers_the_solar_upper_bound(public_cases):
    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    solar = [entry.solar_kwh for entry in request.canonical_hours()]
    compiled = compile_directives(
        request,
        [SolarReductionDirective(note_index=0, structured_adjustment={"hours": [10, 11], "factor": 0.25})],
    )
    model = build_model(request, compiled)

    assert model.upper_bounds[solar_index(10)] == pytest.approx(solar[10] * 0.25)
    assert model.upper_bounds[solar_index(12)] == pytest.approx(solar[12])


def test_grid_cap_becomes_a_grid_upper_bound(public_cases):
    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    compiled = compile_directives(
        request,
        [MaxGridWindowDirective(note_index=0, structured_adjustment={"hours": [19, 20], "max_grid_kwh": 155.0})],
    )
    model = build_model(request, compiled)

    assert model.upper_bounds[grid_index(19)] == pytest.approx(155.0)
    assert np.isinf(model.upper_bounds[grid_index(0)])


def test_reserve_becomes_an_energy_lower_bound(public_cases):
    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    compiled = compile_directives(
        request,
        [
            MinimumBatteryReserveDirective(
                note_index=0, structured_adjustment={"hours": [18, 19], "minimum_energy_kwh": 120.0}
            )
        ],
    )
    model = build_model(request, compiled)

    assert model.lower_bounds[energy_index(18)] == pytest.approx(120.0)
    assert model.lower_bounds[energy_index(0)] == pytest.approx(request.battery.minimum_energy_kwh)
    assert model.upper_bounds[energy_index(0)] == pytest.approx(request.battery.capacity_kwh)


def test_bans_pin_both_the_amount_and_its_mode_variable(public_cases):
    """Pinning the mode variable stops the relaxation buying fractional permission to charge."""
    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    compiled = compile_directives(
        request,
        [
            NoChargeWindowDirective(note_index=0, structured_adjustment={"hours": [2, 3]}),
            NoDischargeWindowDirective(note_index=1, structured_adjustment={"hours": [18]}),
        ],
    )
    model = build_model(request, compiled)

    assert model.upper_bounds[charge_index(2)] == 0.0
    assert model.upper_bounds[charge_mode_index(2)] == 0.0
    assert model.upper_bounds[discharge_index(18)] == 0.0
    assert model.upper_bounds[discharge_mode_index(18)] == 0.0
    # An unaffected hour keeps its full rate.
    assert model.upper_bounds[charge_index(5)] == pytest.approx(request.battery.max_charge_kwh_per_hour)


# ------------------------------------------------------------ the two stages share a model


def test_integrality_marks_only_the_mode_variables(public_cases):
    _, model = _model_for(public_cases[0])

    assert model.integrality.sum() == 48
    assert (model.integrality[CHARGE_MODE] == 1).all()
    assert (model.integrality[DISCHARGE_MODE] == 1).all()
    for block in (GRID, SOLAR, CHARGE, DISCHARGE, ENERGY):
        assert (model.integrality[block] == 0).all()


def test_model_construction_is_deterministic(public_cases):
    """No stage parameter exists, so LP and MILP cannot receive different problems."""
    request, first = _model_for(public_cases[0])
    directives = OptimizeResponse.model_validate(
        public_cases[0]["expected_output"]
    ).directive_interpretation
    second = build_model(request, compile_directives(request, directives))

    assert np.array_equal(first.a_eq, second.a_eq)
    assert np.array_equal(first.b_eq, second.b_eq)
    assert np.array_equal(first.a_ub, second.a_ub)
    assert np.array_equal(first.b_ub, second.b_ub)
    assert np.array_equal(first.objective, second.objective)
    assert np.array_equal(first.lower_bounds, second.lower_bounds)
    assert np.array_equal(first.upper_bounds, second.upper_bounds)


def test_exclusivity_row_forbids_both_modes_at_once(public_cases):
    _, model = _model_for(public_cases[0])
    vector = np.zeros(VARIABLE_COUNT)
    vector[charge_mode_index(9)] = 1.0
    vector[discharge_mode_index(9)] = 1.0

    overshoot = np.maximum(model.a_ub @ vector - model.b_ub, 0.0)
    assert overshoot.max() == pytest.approx(1.0)


def test_mode_link_caps_the_amount(public_cases):
    """``c[h] <= max_charge * yc[h]``: charging with the mode off is infeasible."""
    request, model = _model_for(public_cases[0])
    vector = np.zeros(VARIABLE_COUNT)
    vector[charge_index(9)] = request.battery.max_charge_kwh_per_hour

    overshoot = np.maximum(model.a_ub @ vector - model.b_ub, 0.0)
    assert overshoot.max() == pytest.approx(request.battery.max_charge_kwh_per_hour)


def test_end_of_day_neutrality_is_an_explicit_row(public_cases):
    request, model = _model_for(public_cases[0])
    response = OptimizeResponse.model_validate(public_cases[0]["expected_output"])

    drifted = _vector_from_plan(response)
    drifted[energy_index(23)] += 7.0
    equality_error, _, _ = model.residuals(drifted)

    assert equality_error == pytest.approx(7.0)
    assert model.b_eq[-1] == pytest.approx(request.battery.initial_energy_kwh)
