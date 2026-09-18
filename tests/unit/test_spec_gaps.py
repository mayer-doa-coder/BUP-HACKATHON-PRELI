"""Provisional spec-gap policy tests.

Two different things are asserted here, and the distinction matters:

* The **canonical** window convention (start-inclusive, end-exclusive) comes straight from the
  Problem Statement §05.1 worked examples. These must never change.
* The **provisional** policies (cross-midnight, ``through``, single-hour phrasing, solar
  overlap) are engineering fallbacks. If the organizers clarify one, the expectation here
  changes along with the config default — that is the intended workflow, not a regression.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.policies.spec_gaps import (
    compose_solar_factors,
    expand_window,
    policy_summary,
    single_hour_window,
    through_is_end_exclusive,
)

# ------------------------------------------------------- canonical window convention


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (13, 15, [13, 14]),  # Problem Statement §04.2: "1 PM to 3 PM"
        (14, 16, [14, 15]),  # "between 2 PM and 4 PM"
        (18, 21, [18, 19, 20]),  # "6 PM until 9 PM"
        (12, 14, [12, 13]),  # noon is hour 12
        (0, 2, [0, 1]),  # midnight is hour 0
        (22, 24, [22, 23]),  # end of day
        (16, 17, [16]),  # a single-hour range
    ],
)
def test_windows_are_start_inclusive_and_end_exclusive(start, end, expected):
    assert expand_window(start, end) == expected


def test_degenerate_window_is_empty_rather_than_a_whole_day():
    """``2 PM to 2 PM`` contains no hour; guessing "the whole day" would invent a constraint."""
    assert expand_window(14, 14) == []


@pytest.mark.parametrize(("start", "end"), [(-1, 5), (24, 25), (5, 25)])
def test_out_of_range_endpoints_are_rejected(start, end):
    with pytest.raises(ValueError):
        expand_window(start, end)


# ----------------------------------------------------------- provisional: cross-midnight


def test_cross_midnight_expands_modulo_24_and_serializes_ascending():
    """PROVISIONAL: ``11 PM to 2 AM`` -> {23, 0, 1}, emitted ascending as required."""
    assert expand_window(23, 2) == [0, 1, 23]


def test_window_ending_at_midnight_stops_at_hour_23():
    assert expand_window(23, 0) == [23]
    assert expand_window(21, 0) == [21, 22, 23]


def test_cross_midnight_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("CROSS_MIDNIGHT_POLICY", "reject")
    settings = Settings(_env_file=None)

    with pytest.raises(ValueError):
        expand_window(23, 2, settings=settings)


# -------------------------------------------------- provisional: through / single hour


def test_through_is_end_exclusive_by_default():
    assert through_is_end_exclusive() is True


def test_through_policy_can_be_switched(monkeypatch):
    monkeypatch.setenv("THROUGH_RANGE_POLICY", "end_inclusive")
    assert through_is_end_exclusive(Settings(_env_file=None)) is False


def test_inclusive_end_adds_the_stated_hour():
    assert expand_window(13, 15, inclusive_end=True) == [13, 14, 15]
    assert expand_window(21, 23, inclusive_end=True) == [21, 22, 23]


def test_single_hour_phrase_maps_to_one_interval():
    """PROVISIONAL: "during the 4 PM hour" -> [16]."""
    assert single_hour_window(16) == [16]
    with pytest.raises(ValueError):
        single_hour_window(24)


# ------------------------------------------------------- provisional: solar overlap


def test_first_factor_is_taken_as_is():
    assert compose_solar_factors(None, 0.2) == (0.2, False)


def test_identical_factors_do_not_count_as_ambiguous():
    assert compose_solar_factors(0.5, 0.5) == (0.5, False)


def test_differing_factors_take_the_minimum_and_flag_ambiguity():
    factor, ambiguous = compose_solar_factors(0.8, 0.5)

    assert factor == 0.5
    assert ambiguous is True


def test_zero_factor_is_kept_rather_than_treated_as_missing():
    assert compose_solar_factors(None, 0.0) == (0.0, False)
    assert compose_solar_factors(0.5, 0.0)[0] == 0.0


@pytest.mark.parametrize(
    ("policy", "expected"),
    [("multiply", 0.4), ("last_wins", 0.5), ("min_factor_provisional", 0.5)],
)
def test_overlap_policies(monkeypatch, policy, expected):
    monkeypatch.setenv("SOLAR_OVERLAP_POLICY", policy)
    factor, ambiguous = compose_solar_factors(0.8, 0.5, Settings(_env_file=None))

    assert factor == pytest.approx(expected)
    assert ambiguous is True


def test_policy_summary_lists_every_gap():
    summary = policy_summary()

    assert set(summary) == {"cross_midnight", "through_range", "solar_overlap", "single_hour_phrase"}
    assert all(isinstance(value, str) and value for value in summary.values())
