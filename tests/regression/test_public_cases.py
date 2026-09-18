"""Public-case regression, driven through the same runner the README documents.

Keeping the test and the script on one code path means the command a judge runs and the check
CI runs cannot drift apart.
"""

from __future__ import annotations

import copy

import pytest

from app.validation.interpretation_match import compare_interpretations
from scripts.run_public_cases import run_cases


def test_all_public_cases_pass_the_local_optimizer_path(public_cases):
    results = run_cases(public_cases)

    failures = [f"{result.case_id}: {result.problems}" for result in results if not result.passed]
    assert not failures, "\n".join(failures)
    assert len(results) == 10


def test_all_extended_cases_pass_the_local_optimizer_path(extended_cases):
    results = run_cases(extended_cases)

    failures = [f"{result.case_id}: {result.problems}" for result in results if not result.passed]
    assert not failures, "\n".join(failures)


def test_cost_gap_is_zero_on_every_public_case(public_cases):
    """Matching the published optimum exactly means full optimization credit."""
    for result in run_cases(public_cases):
        assert result.cost_gap == pytest.approx(0.0, abs=0.01), result.case_id


def test_runner_reports_rather_than_raises_on_a_broken_case(public_cases):
    """A regression runner that dies on the first bad case is useless for diagnosis."""
    broken = copy.deepcopy(public_cases[0])
    broken["input"]["battery"]["initial_energy_kwh"] = 10.0
    broken["input"]["battery"]["minimum_energy_kwh"] = 80.0

    results = run_cases([broken])

    assert len(results) == 1
    assert not results[0].passed
    assert results[0].problems


# ------------------------------------------------------- the interpretation comparator


def test_comparator_accepts_the_reference_interpretation(public_cases):
    for case in public_cases:
        expected = case["expected_output"]["directive_interpretation"]
        assert compare_interpretations(expected, expected).matches, case["id"]


def test_comparator_ignores_explanation_wording(public_cases):
    """The rubric says free-text explanation is not matched byte for byte."""
    expected = copy.deepcopy(public_cases[0]["expected_output"]["directive_interpretation"])
    reworded = copy.deepcopy(expected)
    for item in reworded:
        item["explanation"] = "completely different wording here"

    assert compare_interpretations(reworded, expected).matches


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        (lambda item: item.update(directive_type="no_op", structured_adjustment=None), "directive_type"),
        (lambda item: item["structured_adjustment"].update(hours=[1, 2]), "hours"),
        (lambda item: item["structured_adjustment"].update(factor=0.8), "factor"),
        (lambda item: item.update(applies=False), "applies"),
    ],
)
def test_comparator_detects_real_differences(public_cases, mutation, fragment):
    case = next(
        c
        for c in public_cases
        if c["expected_output"]["directive_interpretation"][0]["directive_type"] == "solar_reduction"
    )
    expected = case["expected_output"]["directive_interpretation"]
    actual = copy.deepcopy(expected)
    mutation(actual[0])

    comparison = compare_interpretations(actual, expected)

    assert not comparison.matches
    assert any(fragment in problem for problem in comparison.problems)


def test_comparator_detects_a_missing_entry(public_cases):
    expected = public_cases[5]["expected_output"]["directive_interpretation"]

    comparison = compare_interpretations(expected[:-1], expected)

    assert not comparison.matches
    assert any("entries" in problem for problem in comparison.problems)


def test_comparator_tolerates_numeric_noise_within_judge_tolerance(public_cases):
    case = next(
        c
        for c in public_cases
        if c["expected_output"]["directive_interpretation"][0]["directive_type"]
        == "minimum_battery_reserve"
    )
    expected = case["expected_output"]["directive_interpretation"]
    actual = copy.deepcopy(expected)
    actual[0]["structured_adjustment"]["minimum_energy_kwh"] += 0.005

    assert compare_interpretations(actual, expected).matches
