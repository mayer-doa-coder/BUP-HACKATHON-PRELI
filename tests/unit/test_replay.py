"""Replay validator tests.

Two directions matter equally:

* **No false negatives** — every organizer reference plan, and every extended-pack plan, must
  replay clean. A validator that rejects a valid plan turns a correct answer into a 500.
* **No false positives** — each mutation below breaks exactly one rule, and replay must flag
  that rule. A validator that passes everything is worse than none at all, because the
  service would trust it.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.schemas.request import OptimizeRequest
from app.schemas.response import HourPlan, OptimizeResponse
from app.validation.replay import ViolationCode, derive_envelope, replay

# The reference plans are quoted to two decimals at most, so judge tolerance is the honest
# yardstick for them. The service's own plans are replayed at internal tolerance (1e-7).
REFERENCE_TOLERANCE = 0.01


def _parse(case) -> tuple[OptimizeRequest, OptimizeResponse]:
    return (
        OptimizeRequest.model_validate(case["input"]),
        OptimizeResponse.model_validate(case["expected_output"]),
    )


# ------------------------------------------------------------------ no false negatives


def test_every_public_reference_plan_replays_clean(public_cases):
    failures = []
    for case in public_cases:
        request, response = _parse(case)
        report = replay(
            request,
            response.directive_interpretation,
            response,
            tolerance=REFERENCE_TOLERANCE,
        )
        if not report.ok:
            failures.append(f"{case['id']}: {report.messages}")
    assert not failures, "\n".join(failures)


def test_every_extended_reference_plan_replays_clean(extended_cases):
    failures = []
    for case in extended_cases:
        request, response = _parse(case)
        report = replay(
            request,
            response.directive_interpretation,
            response,
            tolerance=REFERENCE_TOLERANCE,
        )
        if not report.ok:
            failures.append(f"{case['id']}: {report.messages}")
    assert not failures, "\n".join(failures)


def test_clean_replay_reports_near_zero_residuals(public_cases):
    request, response = _parse(public_cases[0])
    report = replay(request, response.directive_interpretation, response, tolerance=REFERENCE_TOLERANCE)

    # The reference data is exact, so the residuals are not merely "inside judge tolerance" —
    # they are at machine precision. Asserting that keeps a sloppy future change visible.
    assert report.ok
    assert report.max_balance_error < 1e-9
    assert report.max_state_error < 1e-9
    assert report.final_energy_error < 1e-9
    assert report.recalculated_total_cost_bdt == pytest.approx(response.total_cost_bdt, abs=1e-9)


# ------------------------------------------------------------------ no false positives


def _mutate(case, mutation) -> tuple[OptimizeRequest, OptimizeResponse]:
    """Apply ``mutation`` to a deep copy of the expected output and reparse it.

    Response-model validators are bypassed with ``model_construct`` where the mutation is one
    the schema itself would refuse, so that replay — not Pydantic — is what is under test.
    """
    body = copy.deepcopy(case["expected_output"])
    mutation(body)
    request = OptimizeRequest.model_validate(case["input"])
    try:
        response = OptimizeResponse.model_validate(body)
    except ValidationError:
        pristine = OptimizeResponse.model_validate(case["expected_output"])
        response = OptimizeResponse.model_construct(
            scenario_id=body["scenario_id"],
            directive_interpretation=pristine.directive_interpretation,
            hourly_plan=[HourPlan.model_construct(**entry) for entry in body["hourly_plan"]],
            total_grid_kwh=body["total_grid_kwh"],
            total_cost_bdt=body["total_cost_bdt"],
            peak_grid_kwh=body["peak_grid_kwh"],
            plan_summary=body["plan_summary"],
        )
    return request, response


def _first_hour_with(body, action: str) -> dict:
    return next(entry for entry in body["hourly_plan"] if entry["battery_action"] == action)


def _break_balance(body):
    body["hourly_plan"][7]["grid_kwh"] += 25.0


def _break_state(body):
    body["hourly_plan"][3]["battery_energy_after_kwh"] += 12.0


def _break_final_neutrality(body):
    body["hourly_plan"][23]["battery_energy_after_kwh"] += 30.0


def _idle_with_magnitude(body):
    entry = _first_hour_with(body, "idle")
    entry["battery_kwh"] = 9.0


def _negative_grid(body):
    body["hourly_plan"][2]["grid_kwh"] = -5.0


def _wrong_total_grid(body):
    body["total_grid_kwh"] += 15.0


def _wrong_total_cost(body):
    body["total_cost_bdt"] += 250.0


def _wrong_peak(body):
    body["peak_grid_kwh"] += 40.0


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (_break_balance, ViolationCode.ENERGY_BALANCE),
        (_break_state, ViolationCode.STATE_TRANSITION),
        (_break_final_neutrality, ViolationCode.FINAL_ENERGY_NOT_NEUTRAL),
        (_idle_with_magnitude, ViolationCode.IDLE_MAGNITUDE),
        (_negative_grid, ViolationCode.NEGATIVE_VALUE),
        (_wrong_total_grid, ViolationCode.TOTAL_GRID_MISMATCH),
        (_wrong_total_cost, ViolationCode.TOTAL_COST_MISMATCH),
        (_wrong_peak, ViolationCode.PEAK_GRID_MISMATCH),
    ],
)
def test_mutations_are_caught_with_the_right_code(public_cases, mutation, expected_code):
    request, response = _mutate(public_cases[0], mutation)
    report = replay(request, response.directive_interpretation, response, tolerance=REFERENCE_TOLERANCE)

    assert not report.ok
    assert expected_code in report.codes, report.messages


def test_scenario_id_must_be_echoed(public_cases):
    def _swap_id(body):
        body["scenario_id"] = "SOMETHING-ELSE"

    request, response = _mutate(public_cases[0], _swap_id)
    report = replay(request, response.directive_interpretation, response, tolerance=REFERENCE_TOLERANCE)

    assert ViolationCode.SCENARIO_ID_MISMATCH in report.codes


def test_missing_interpretation_entry_is_caught(public_cases):
    case = next(c for c in public_cases if len(c["input"]["operator_notes"]) > 1)
    request, response = _parse(case)
    trimmed = response.model_copy(update={"directive_interpretation": response.directive_interpretation[:1]})

    report = replay(request, trimmed.directive_interpretation, trimmed, tolerance=REFERENCE_TOLERANCE)

    assert ViolationCode.INTERPRETATION_COUNT in report.codes


# ---------------------------------------------- directive constraints are really enforced


def test_charging_during_a_no_charge_window_is_caught(public_cases):
    """SAMPLE-02's own plan, replayed against its own directive, but with a charge injected."""
    case = next(
        c
        for c in public_cases
        if any(d["directive_type"] == "no_charge_window" for d in c["expected_output"]["directive_interpretation"])
    )
    banned_hour = next(
        d["structured_adjustment"]["hours"][0]
        for d in case["expected_output"]["directive_interpretation"]
        if d["directive_type"] == "no_charge_window"
    )

    def _charge_in_banned_hour(body):
        entry = next(e for e in body["hourly_plan"] if e["hour"] == banned_hour)
        entry["battery_action"] = "charge"
        entry["battery_kwh"] = 10.0

    request, response = _mutate(case, _charge_in_banned_hour)
    report = replay(request, response.directive_interpretation, response, tolerance=REFERENCE_TOLERANCE)

    assert ViolationCode.CHARGE_DURING_BAN in report.codes, report.messages


def test_discharging_during_a_no_discharge_window_is_caught(public_cases):
    case = next(
        c
        for c in public_cases
        if any(
            d["directive_type"] == "no_discharge_window" for d in c["expected_output"]["directive_interpretation"]
        )
    )
    banned_hour = next(
        d["structured_adjustment"]["hours"][0]
        for d in case["expected_output"]["directive_interpretation"]
        if d["directive_type"] == "no_discharge_window"
    )

    def _discharge_in_banned_hour(body):
        entry = next(e for e in body["hourly_plan"] if e["hour"] == banned_hour)
        entry["battery_action"] = "discharge"
        entry["battery_kwh"] = 10.0

    request, response = _mutate(case, _discharge_in_banned_hour)
    report = replay(request, response.directive_interpretation, response, tolerance=REFERENCE_TOLERANCE)

    assert ViolationCode.DISCHARGE_DURING_BAN in report.codes, report.messages


def test_exceeding_a_grid_cap_is_caught(public_cases):
    case = next(
        c
        for c in public_cases
        if any(d["directive_type"] == "max_grid_window" for d in c["expected_output"]["directive_interpretation"])
    )
    directive = next(
        d for d in case["expected_output"]["directive_interpretation"] if d["directive_type"] == "max_grid_window"
    )
    capped_hour = directive["structured_adjustment"]["hours"][0]
    cap = directive["structured_adjustment"]["max_grid_kwh"]

    def _blow_the_cap(body):
        entry = next(e for e in body["hourly_plan"] if e["hour"] == capped_hour)
        entry["grid_kwh"] = cap + 50.0

    request, response = _mutate(case, _blow_the_cap)
    report = replay(request, response.directive_interpretation, response, tolerance=REFERENCE_TOLERANCE)

    assert ViolationCode.GRID_CAP_EXCEEDED in report.codes, report.messages


def test_dipping_below_a_directive_reserve_is_caught(public_cases):
    case = next(
        c
        for c in public_cases
        if any(
            d["directive_type"] == "minimum_battery_reserve"
            for d in c["expected_output"]["directive_interpretation"]
        )
    )
    directive = next(
        d
        for d in case["expected_output"]["directive_interpretation"]
        if d["directive_type"] == "minimum_battery_reserve"
    )
    reserved_hour = directive["structured_adjustment"]["hours"][0]
    floor = directive["structured_adjustment"]["minimum_energy_kwh"]

    def _dip_below_reserve(body):
        entry = next(e for e in body["hourly_plan"] if e["hour"] == reserved_hour)
        entry["battery_energy_after_kwh"] = floor - 10.0

    request, response = _mutate(case, _dip_below_reserve)
    report = replay(request, response.directive_interpretation, response, tolerance=REFERENCE_TOLERANCE)

    assert ViolationCode.BATTERY_BELOW_MINIMUM in report.codes, report.messages


def test_overusing_reduced_solar_is_caught(public_cases):
    """The reduced-solar bound is what the judge recomputes; using pre-reduction solar must fail."""
    case = next(
        c
        for c in public_cases
        if any(d["directive_type"] == "solar_reduction" for d in c["expected_output"]["directive_interpretation"])
    )
    directive = next(
        d for d in case["expected_output"]["directive_interpretation"] if d["directive_type"] == "solar_reduction"
    )
    reduced_hour = directive["structured_adjustment"]["hours"][0]
    original_solar = next(h["solar_kwh"] for h in case["input"]["hours"] if h["hour"] == reduced_hour)

    def _use_unreduced_solar(body):
        entry = next(e for e in body["hourly_plan"] if e["hour"] == reduced_hour)
        entry["solar_used_kwh"] = original_solar

    request, response = _mutate(case, _use_unreduced_solar)
    report = replay(request, response.directive_interpretation, response, tolerance=REFERENCE_TOLERANCE)

    assert ViolationCode.SOLAR_OVERUSE in report.codes, report.messages


def test_exceeding_the_charge_rate_is_caught(public_cases):
    case = public_cases[0]

    def _overcharge(body):
        entry = _first_hour_with(body, "charge")
        entry["battery_kwh"] = case["input"]["battery"]["max_charge_kwh_per_hour"] + 40.0

    request, response = _mutate(case, _overcharge)
    report = replay(request, response.directive_interpretation, response, tolerance=REFERENCE_TOLERANCE)

    assert ViolationCode.CHARGE_RATE_EXCEEDED in report.codes, report.messages


def test_exceeding_capacity_is_caught(public_cases):
    case = public_cases[0]

    def _overfill(body):
        entry = body["hourly_plan"][4]
        entry["battery_energy_after_kwh"] = case["input"]["battery"]["capacity_kwh"] + 25.0

    request, response = _mutate(case, _overfill)
    report = replay(request, response.directive_interpretation, response, tolerance=REFERENCE_TOLERANCE)

    assert ViolationCode.BATTERY_ABOVE_CAPACITY in report.codes, report.messages


# ------------------------------------------------------------------- envelope derivation


def test_envelope_applies_the_solar_factor(public_cases):
    case = next(
        c
        for c in public_cases
        if any(d["directive_type"] == "solar_reduction" for d in c["expected_output"]["directive_interpretation"])
    )
    request, response = _parse(case)
    directive = next(
        d for d in response.directive_interpretation if d.directive_type == "solar_reduction"
    )

    envelope = derive_envelope(request, response.directive_interpretation)
    solar_by_hour = {entry.hour: entry.solar_kwh for entry in request.canonical_hours()}

    for hour in directive.structured_adjustment.hours:
        expected = solar_by_hour[hour] * directive.structured_adjustment.factor
        assert envelope.effective_solar[hour] == pytest.approx(expected)
    untouched = set(range(24)) - set(directive.structured_adjustment.hours)
    for hour in untouched:
        assert envelope.effective_solar[hour] == pytest.approx(solar_by_hour[hour])


def test_envelope_composes_overlapping_directives(public_cases):
    """Reserves take the pointwise max, caps the pointwise min, bans stay hard."""
    from app.schemas.directive import (
        MaxGridWindowDirective,
        MinimumBatteryReserveDirective,
        NoChargeWindowDirective,
        NoDischargeWindowDirective,
    )

    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    base_minimum = request.battery.minimum_energy_kwh
    directives = [
        MinimumBatteryReserveDirective(
            note_index=0, structured_adjustment={"hours": [18, 19], "minimum_energy_kwh": base_minimum + 50}
        ),
        MinimumBatteryReserveDirective(
            note_index=1, structured_adjustment={"hours": [19, 20], "minimum_energy_kwh": base_minimum + 20}
        ),
        MaxGridWindowDirective(note_index=2, structured_adjustment={"hours": [19], "max_grid_kwh": 150.0}),
    ]
    envelope = derive_envelope(request, directives)

    assert envelope.min_energy[18] == pytest.approx(base_minimum + 50)
    assert envelope.min_energy[19] == pytest.approx(base_minimum + 50)  # max, not last-wins
    assert envelope.min_energy[20] == pytest.approx(base_minimum + 20)
    assert envelope.min_energy[0] == pytest.approx(base_minimum)
    assert envelope.grid_upper[19] == pytest.approx(150.0)

    both_banned = derive_envelope(
        request,
        [
            NoChargeWindowDirective(note_index=0, structured_adjustment={"hours": [15]}),
            NoDischargeWindowDirective(note_index=1, structured_adjustment={"hours": [15]}),
        ],
    )
    assert both_banned.charge_allowed[15] is False
    assert both_banned.discharge_allowed[15] is False


def test_overlapping_grid_caps_take_the_minimum(public_cases):
    from app.schemas.directive import MaxGridWindowDirective

    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    envelope = derive_envelope(
        request,
        [
            MaxGridWindowDirective(note_index=0, structured_adjustment={"hours": [19, 20], "max_grid_kwh": 180.0}),
            MaxGridWindowDirective(note_index=1, structured_adjustment={"hours": [20, 21], "max_grid_kwh": 120.0}),
        ],
    )

    assert envelope.grid_upper[19] == pytest.approx(180.0)
    assert envelope.grid_upper[20] == pytest.approx(120.0)
    assert envelope.grid_upper[21] == pytest.approx(120.0)


def test_zero_valued_directives_are_not_lost_to_truthiness(public_cases):
    """factor=0.0 and max_grid_kwh=0.0 are real constraints, not "unset"."""
    from app.schemas.directive import MaxGridWindowDirective, SolarReductionDirective

    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    envelope = derive_envelope(
        request,
        [
            SolarReductionDirective(note_index=0, structured_adjustment={"hours": [10, 11], "factor": 0.0}),
            MaxGridWindowDirective(note_index=1, structured_adjustment={"hours": [14], "max_grid_kwh": 0.0}),
        ],
    )

    assert envelope.effective_solar[10] == 0.0
    assert envelope.effective_solar[11] == 0.0
    assert envelope.grid_upper[14] == 0.0


def test_no_op_directives_change_nothing(public_cases):
    from app.schemas.directive import NoOpDirective

    request = OptimizeRequest.model_validate(public_cases[0]["input"])
    baseline = derive_envelope(request, [])
    with_no_op = derive_envelope(request, [NoOpDirective(note_index=0)])

    assert with_no_op == baseline


# ------------------------------------------------------------------------ independence


def test_replay_does_not_import_the_optimizer():
    """D-09: shared code between plan builder and validator would let a bug approve itself.

    The import graph is inspected rather than the source text, so prose that merely *mentions*
    the optimizer (as the module docstring does, deliberately) does not trip the check.
    """
    import ast
    import pathlib

    module_path = pathlib.Path("app/validation/replay.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    offenders = [name for name in imported if name.startswith("app.optimizer")]
    assert not offenders, f"replay must stay independent of the optimizer, but imports {offenders}"
