"""Schema tests against the organizer's own worked examples.

The strongest available check on the canonical models is that every published reference
request and response round-trips through them unchanged. If a model is too strict, a real
organizer example fails to parse; if it is too loose, the fail-closed validators below catch it.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.schemas.directive import NoOpDirective, SolarReductionDirective
from app.schemas.request import OptimizeRequest
from app.schemas.response import OptimizeResponse

CANONICAL_RESPONSE_FIELDS = {
    "scenario_id",
    "directive_interpretation",
    "hourly_plan",
    "total_grid_kwh",
    "total_cost_bdt",
    "peak_grid_kwh",
    "plan_summary",
}


def test_every_public_input_parses(public_cases):
    for case in public_cases:
        request = OptimizeRequest.model_validate(case["input"])
        assert [entry.hour for entry in request.canonical_hours()] == list(range(24))


def test_every_public_expected_output_parses_and_round_trips(public_cases):
    for case in public_cases:
        expected = case["expected_output"]
        response = OptimizeResponse.model_validate(expected)
        dumped = response.model_dump(mode="json")

        assert set(dumped) == CANONICAL_RESPONSE_FIELDS, case["id"]
        assert dumped["directive_interpretation"] == expected["directive_interpretation"], case["id"]
        assert dumped["hourly_plan"] == expected["hourly_plan"], case["id"]


def test_extended_expected_outputs_parse(extended_cases):
    for case in extended_cases:
        OptimizeResponse.model_validate(case["expected_output"])


def test_no_op_serializes_an_explicit_null_adjustment():
    directive = NoOpDirective(note_index=1, explanation="Not a schedule constraint.")
    dumped = directive.model_dump(mode="json")

    assert dumped["applies"] is False
    assert dumped["directive_type"] == "no_op"
    assert "structured_adjustment" in dumped
    assert dumped["structured_adjustment"] is None


def test_no_op_cannot_carry_an_adjustment():
    with pytest.raises(ValidationError):
        NoOpDirective(note_index=0, structured_adjustment={"hours": [13]})


def test_actionable_directive_cannot_set_applies_false():
    with pytest.raises(ValidationError):
        SolarReductionDirective(
            note_index=0,
            applies=False,
            structured_adjustment={"hours": [13, 14], "factor": 0.2},
        )


@pytest.mark.parametrize(
    "hours",
    [
        [13, 13, 14],  # duplicate
        [14, 13],  # unsorted
        [23, 24],  # out of range
        [],  # empty window
    ],
)
def test_invalid_hour_sets_are_rejected(hours):
    with pytest.raises(ValidationError):
        SolarReductionDirective(note_index=0, structured_adjustment={"hours": hours, "factor": 0.5})


@pytest.mark.parametrize("factor", [1.5, -0.1, float("nan"), float("inf")])
def test_factor_outside_zero_to_one_is_rejected(factor):
    with pytest.raises(ValidationError):
        SolarReductionDirective(note_index=0, structured_adjustment={"hours": [13], "factor": factor})


@pytest.mark.parametrize("factor", [0.0, 1.0, 0.125])
def test_boundary_factors_are_accepted(factor):
    """factor=0.0 is a real directive ("PV unavailable") and must survive every check."""
    directive = SolarReductionDirective(note_index=0, structured_adjustment={"hours": [13], "factor": factor})

    assert directive.structured_adjustment.factor == factor


def test_response_rejects_an_extra_field(public_cases):
    body = copy.deepcopy(public_cases[0]["expected_output"])
    body["solver_debug"] = {"status": "optimal"}

    with pytest.raises(ValidationError):
        OptimizeResponse.model_validate(body)


def test_response_rejects_out_of_order_plan(public_cases):
    body = copy.deepcopy(public_cases[0]["expected_output"])
    body["hourly_plan"][0], body["hourly_plan"][1] = body["hourly_plan"][1], body["hourly_plan"][0]

    with pytest.raises(ValidationError):
        OptimizeResponse.model_validate(body)


def test_response_rejects_idle_with_magnitude(public_cases):
    body = copy.deepcopy(public_cases[0]["expected_output"])
    for entry in body["hourly_plan"]:
        if entry["battery_action"] == "idle":
            entry["battery_kwh"] = 5.0
            break

    with pytest.raises(ValidationError):
        OptimizeResponse.model_validate(body)


def test_request_ignores_array_position_and_uses_the_hour_field(public_cases):
    body = copy.deepcopy(public_cases[0]["input"])
    body["hours"].reverse()

    request = OptimizeRequest.model_validate(body)

    assert [entry.hour for entry in request.canonical_hours()] == list(range(24))
    original = {entry["hour"]: entry["demand_kwh"] for entry in public_cases[0]["input"]["hours"]}
    assert all(entry.demand_kwh == original[entry.hour] for entry in request.canonical_hours())
