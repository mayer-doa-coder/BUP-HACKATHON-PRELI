"""Deterministic guardrail tests.

Three obligations, in order of how expensive it is to get them wrong:

1. **Never reject valid output.** Every published reference interpretation must pass untouched;
   a false rejection turns a correct answer into a wasted repair or a 500.
2. **Never admit invalid output.** Each fixture breaks exactly one rule and must be caught with
   the matching :class:`GuardrailCode`, because P10 routes on that code.
3. **Never "fix" semantics.** Duplicated hours, out-of-range factors and unknown types are
   reported, not quietly repaired into something plausible.

The ``GR-*`` cases come from the adversarial pack, so the expectations are the corpus's, not mine.
"""

from __future__ import annotations

import copy

import pytest

from app.guardrails.directive_validator import GuardrailCode, validate_directives
from app.guardrails.normalizer import (
    normalize_explanation,
    normalize_negative_zero,
    sort_entries_by_note_index,
    sort_hours,
)
from app.schemas.request import OptimizeRequest


def _request(case, note_count: int | None = None) -> OptimizeRequest:
    body = copy.deepcopy(case["input"])
    if note_count is not None:
        body["operator_notes"] = ["note"] * note_count
    return OptimizeRequest.model_validate(body)


def _entry(**overrides):
    entry = {
        "note_index": 0,
        "applies": True,
        "directive_type": "no_charge_window",
        "structured_adjustment": {"hours": [14, 15]},
        "explanation": "x",
    }
    entry.update(overrides)
    return entry


# --------------------------------------------------------------- valid output passes


def test_every_reference_interpretation_passes_untouched(public_cases, extended_cases):
    failures = []
    for case in [*public_cases, *extended_cases]:
        request = OptimizeRequest.model_validate(case["input"])
        report = validate_directives(case["expected_output"]["directive_interpretation"], request)

        if not report.ok:
            failures.append(f"{case['id']}: {report.messages}")
        elif report.normalizations:
            failures.append(f"{case['id']}: needlessly normalized {report.normalizations}")
    assert not failures, "\n".join(failures)


def test_validated_directives_are_canonical_models(public_cases):
    request = OptimizeRequest.model_validate(public_cases[5]["input"])
    report = validate_directives(public_cases[5]["expected_output"]["directive_interpretation"], request)

    assert report.ok
    assert [item.note_index for item in report.directives] == [0, 1, 2]
    assert report.directives[2].directive_type == "no_op"
    assert report.directives[2].structured_adjustment is None


def test_zero_valued_directives_survive(public_cases):
    """factor=0.0 and max_grid_kwh=0.0 are real constraints, not missing ones."""
    request = _request(public_cases[0], note_count=2)
    report = validate_directives(
        [
            _entry(directive_type="solar_reduction", structured_adjustment={"hours": [10], "factor": 0.0}),
            _entry(
                note_index=1,
                directive_type="max_grid_window",
                structured_adjustment={"hours": [14], "max_grid_kwh": 0.0},
            ),
        ],
        request,
    )

    assert report.ok, report.messages
    assert report.directives[0].structured_adjustment.factor == 0.0
    assert report.directives[1].structured_adjustment.max_grid_kwh == 0.0


# ------------------------------------------------- the adversarial pack's own fixtures


GR_EXPECTED_CODES = {
    "GR-01": GuardrailCode.DUPLICATE_HOURS,
    "GR-03": GuardrailCode.UNKNOWN_DIRECTIVE_TYPE,
    "GR-04": GuardrailCode.NO_OP_WITH_ADJUSTMENT,
    "GR-05": GuardrailCode.APPLIES_MISMATCH,
    "GR-06": GuardrailCode.FACTOR_OUT_OF_RANGE,
    "GR-07": GuardrailCode.GRID_CAP_NEGATIVE,
    "GR-08": GuardrailCode.RESERVE_ABOVE_CAPACITY,
    "GR-11": GuardrailCode.HOUR_OUT_OF_RANGE,
    "GR-12": GuardrailCode.ADJUSTMENT_SHAPE,
}


def test_adversarial_guardrail_fixtures_are_rejected_with_the_right_code(adversarial_pack, public_cases):
    cases = {case["id"]: case for case in adversarial_pack["guardrail_output_cases"]}
    problems = []

    for case_id, expected_code in GR_EXPECTED_CODES.items():
        fixture = cases[case_id]
        request = _request(public_cases[0], note_count=1)
        report = validate_directives([fixture["llm_output"]], request)

        if report.ok:
            problems.append(f"{case_id} ({fixture['description']}) was accepted but must be rejected")
        elif expected_code not in report.codes:
            problems.append(f"{case_id}: expected {expected_code}, got {report.codes}")

    assert not problems, "\n".join(problems)


def test_missing_note_index_mapping_is_caught(adversarial_pack, public_cases):
    """GR-09: two notes, one interpretation."""
    fixture = next(c for c in adversarial_pack["guardrail_output_cases"] if c["id"] == "GR-09")
    request = _request(public_cases[0], note_count=2)

    report = validate_directives(fixture["llm_output"], request)

    assert GuardrailCode.WRONG_ENTRY_COUNT in report.codes
    assert GuardrailCode.MISSING_NOTE_INDEX in report.codes


def test_duplicate_note_index_is_caught(adversarial_pack, public_cases):
    """GR-10: two entries, both claiming note 0."""
    fixture = next(c for c in adversarial_pack["guardrail_output_cases"] if c["id"] == "GR-10")
    request = _request(public_cases[0], note_count=2)

    report = validate_directives(fixture["llm_output"], request)

    assert GuardrailCode.DUPLICATE_NOTE_INDEX in report.codes


def test_unsorted_hours_are_canonicalized_not_rejected(adversarial_pack, public_cases):
    """GR-02 allows either policy. Sorting is chosen deliberately.

    A window is a *set* of hours, so ordering carries no information and sorting loses nothing.
    Rejecting would spend a repair round trip — and possibly the whole case — on a difference
    that cannot change the resulting constraint.
    """
    fixture = next(c for c in adversarial_pack["guardrail_output_cases"] if c["id"] == "GR-02")
    request = _request(public_cases[0], note_count=1)

    report = validate_directives([fixture["llm_output"]], request)

    assert report.ok, report.messages
    assert report.directives[0].structured_adjustment.hours == [14, 15]
    assert any("sorted hours" in note for note in report.normalizations)


# ------------------------------------------------------------ never repair semantics


def test_duplicate_hours_are_never_deduplicated(public_cases):
    request = _request(public_cases[0], note_count=1)

    report = validate_directives(
        [_entry(structured_adjustment={"hours": [13, 13, 14]})], request
    )

    assert GuardrailCode.DUPLICATE_HOURS in report.codes
    assert not report.directives


@pytest.mark.parametrize("factor", [1.8, -0.1])
def test_out_of_range_factor_is_never_clipped(public_cases, factor):
    request = _request(public_cases[0], note_count=1)

    report = validate_directives(
        [_entry(directive_type="solar_reduction", structured_adjustment={"hours": [13], "factor": factor})],
        request,
    )

    assert GuardrailCode.FACTOR_OUT_OF_RANGE in report.codes
    assert not report.directives


def test_out_of_range_hour_is_never_clipped(public_cases):
    request = _request(public_cases[0], note_count=1)

    report = validate_directives([_entry(structured_adjustment={"hours": [23, 24]})], request)

    assert GuardrailCode.HOUR_OUT_OF_RANGE in report.codes


def test_unknown_directive_type_is_never_coerced(public_cases):
    request = _request(public_cases[0], note_count=1)

    report = validate_directives([_entry(directive_type="battery_shutdown")], request)

    assert GuardrailCode.UNKNOWN_DIRECTIVE_TYPE in report.codes
    assert not report.directives


def test_reserve_above_capacity_is_scenario_dependent(public_cases):
    """The same number is valid for one battery and impossible for another."""
    case = public_cases[0]
    capacity = case["input"]["battery"]["capacity_kwh"]
    entry = _entry(
        directive_type="minimum_battery_reserve",
        structured_adjustment={"hours": [18], "minimum_energy_kwh": capacity + 1},
    )

    rejected = validate_directives([entry], _request(case, note_count=1))
    assert GuardrailCode.RESERVE_ABOVE_CAPACITY in rejected.codes

    bigger_battery = copy.deepcopy(case["input"])
    bigger_battery["operator_notes"] = ["note"]
    bigger_battery["battery"]["capacity_kwh"] = capacity * 2
    accepted = validate_directives([entry], OptimizeRequest.model_validate(bigger_battery))
    assert accepted.ok, accepted.messages


# ----------------------------------------------------------------- hostile payloads


@pytest.mark.parametrize(
    ("entry_overrides", "expected_code"),
    [
        ({"note_index": "0"}, GuardrailCode.NOTE_INDEX_NOT_INTEGER),
        ({"note_index": True}, GuardrailCode.NOTE_INDEX_NOT_INTEGER),
        ({"note_index": 7}, GuardrailCode.NOTE_INDEX_OUT_OF_RANGE),
        ({"applies": "yes"}, GuardrailCode.APPLIES_NOT_BOOLEAN),
        ({"structured_adjustment": None}, GuardrailCode.ADJUSTMENT_MISSING),
        ({"structured_adjustment": [1, 2]}, GuardrailCode.ADJUSTMENT_SHAPE),
        ({"structured_adjustment": {"hours": "13-15"}}, GuardrailCode.HOURS_NOT_A_LIST),
        ({"structured_adjustment": {"hours": []}}, GuardrailCode.HOURS_EMPTY),
        ({"structured_adjustment": {"hours": [13.5]}}, GuardrailCode.HOUR_NOT_INTEGER),
        ({"structured_adjustment": {"hours": [True]}}, GuardrailCode.HOUR_NOT_INTEGER),
        ({"structured_adjustment": {"hours": [14], "extra": 1}}, GuardrailCode.ADJUSTMENT_SHAPE),
    ],
)
def test_malformed_entries_are_classified(public_cases, entry_overrides, expected_code):
    request = _request(public_cases[0], note_count=1)

    report = validate_directives([_entry(**entry_overrides)], request)

    assert expected_code in report.codes, report.messages


@pytest.mark.parametrize(
    ("directive_type", "field_name", "value", "expected_code"),
    [
        ("solar_reduction", "factor", float("nan"), GuardrailCode.FACTOR_NOT_A_NUMBER),
        ("solar_reduction", "factor", float("inf"), GuardrailCode.FACTOR_NOT_A_NUMBER),
        ("solar_reduction", "factor", "0.2", GuardrailCode.FACTOR_NOT_A_NUMBER),
        ("minimum_battery_reserve", "minimum_energy_kwh", float("nan"), GuardrailCode.RESERVE_NOT_A_NUMBER),
        ("minimum_battery_reserve", "minimum_energy_kwh", -5, GuardrailCode.RESERVE_NEGATIVE),
        ("max_grid_window", "max_grid_kwh", float("inf"), GuardrailCode.GRID_CAP_NOT_A_NUMBER),
        ("max_grid_window", "max_grid_kwh", -5, GuardrailCode.GRID_CAP_NEGATIVE),
    ],
)
def test_non_finite_and_out_of_domain_numbers_are_classified(
    public_cases, directive_type, field_name, value, expected_code
):
    request = _request(public_cases[0], note_count=1)
    entry = _entry(
        directive_type=directive_type,
        structured_adjustment={"hours": [13], field_name: value},
    )

    report = validate_directives([entry], request)

    assert expected_code in report.codes, report.messages


def test_non_object_entry_is_rejected(public_cases):
    request = _request(public_cases[0], note_count=1)

    report = validate_directives(["not an object"], request)

    assert GuardrailCode.NOT_AN_OBJECT in report.codes


def test_all_failures_are_collected_not_just_the_first(public_cases):
    """A repair prompt listing every problem has a better chance of one-shot success."""
    request = _request(public_cases[0], note_count=1)
    entry = _entry(
        directive_type="solar_reduction",
        structured_adjustment={"hours": [24, 13, 13], "factor": 5.0},
    )

    report = validate_directives([entry], request)

    assert GuardrailCode.DUPLICATE_HOURS in report.codes
    assert GuardrailCode.FACTOR_OUT_OF_RANGE in report.codes
    assert len(report.failures) >= 2


def test_missing_explanation_is_filled_rather_than_rejected(public_cases):
    """Explanation is free text the rubric does not match; failing a case over it is a bad trade."""
    request = _request(public_cases[0], note_count=1)
    entry = _entry()
    del entry["explanation"]

    report = validate_directives([entry], request)

    assert report.ok, report.messages
    assert report.directives[0].explanation == ""


def test_entries_returned_out_of_order_are_sorted(public_cases):
    request = _request(public_cases[0], note_count=2)
    entries = [
        _entry(note_index=1, structured_adjustment={"hours": [20]}),
        _entry(note_index=0, structured_adjustment={"hours": [14]}),
    ]

    report = validate_directives(entries, request)

    assert report.ok, report.messages
    assert [item.note_index for item in report.directives] == [0, 1]
    assert "sorted entries by note_index" in report.normalizations


# -------------------------------------------------------------------- the normalizer


def test_sorting_entries_refuses_when_indices_are_not_unique():
    items = [{"note_index": 0}, {"note_index": 0}]

    ordered, changed = sort_entries_by_note_index(items)

    assert ordered is items
    assert changed is False


def test_sorting_hours_refuses_when_hours_repeat():
    hours = [15, 13, 13]

    ordered, changed = sort_hours(hours)

    assert ordered is hours
    assert changed is False


def test_negative_zero_is_canonicalized():
    assert normalize_negative_zero(-0.0) == 0.0
    assert str(normalize_negative_zero(-0.0)) == "0.0"
    assert normalize_negative_zero(4.5) == 4.5


def test_explanation_normalization():
    assert normalize_explanation("  spaced  ") == ("spaced", True)
    assert normalize_explanation("clean") == ("clean", False)
    assert normalize_explanation(None) == ("", True)
    assert normalize_explanation(42)[0] == "42"
