"""Compare an interpretation against a reference interpretation.

Used by the regression runner and the semantic corpus, never on the judge path. It encodes
what the organizers actually check (Problem Statement §11.1): relevance, directive type,
affected hours, and numeric values within tolerance. Free-text ``explanation`` wording is
explicitly **not** compared — the rubric says it is not matched byte for byte.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

# The organizer tolerance for numeric comparisons.
NUMERIC_TOLERANCE = 0.01


@dataclass(frozen=True)
class InterpretationDiff:
    """Per-note comparison outcome."""

    note_index: int
    matches: bool
    problems: tuple[str, ...] = ()


@dataclass
class InterpretationComparison:
    matches: bool = True
    diffs: list[InterpretationDiff] = field(default_factory=list)

    @property
    def problems(self) -> list[str]:
        return [
            f"note {diff.note_index}: {problem}" for diff in self.diffs for problem in diff.problems
        ]


def compare_interpretations(
    actual: Sequence[Any],
    expected: Sequence[Any],
    *,
    tolerance: float = NUMERIC_TOLERANCE,
) -> InterpretationComparison:
    """Compare two interpretation lists item by item.

    Both sides may be Pydantic models or plain dicts, so the runner can compare a parsed
    response against raw JSON from the case pack without converting either.
    """
    comparison = InterpretationComparison()

    if len(actual) != len(expected):
        comparison.matches = False
        comparison.diffs.append(
            InterpretationDiff(
                note_index=-1,
                matches=False,
                problems=(f"expected {len(expected)} interpretation entries, got {len(actual)}",),
            )
        )
        return comparison

    for position, (actual_item, expected_item) in enumerate(zip(actual, expected, strict=True)):
        problems = _compare_one(_as_dict(actual_item), _as_dict(expected_item), position, tolerance)
        comparison.diffs.append(
            InterpretationDiff(note_index=position, matches=not problems, problems=tuple(problems))
        )
        if problems:
            comparison.matches = False

    return comparison


def _as_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    return item.model_dump(mode="json")


def _compare_one(
    actual: dict[str, Any], expected: dict[str, Any], position: int, tolerance: float
) -> list[str]:
    problems: list[str] = []

    if actual.get("note_index") != position:
        problems.append(f"note_index is {actual.get('note_index')}, expected {position}")
    if actual.get("directive_type") != expected.get("directive_type"):
        problems.append(
            f"directive_type {actual.get('directive_type')!r} != {expected.get('directive_type')!r}"
        )
        # A wrong type makes the adjustment comparison meaningless.
        return problems
    if bool(actual.get("applies")) != bool(expected.get("applies")):
        problems.append(f"applies {actual.get('applies')} != {expected.get('applies')}")

    actual_adjustment = actual.get("structured_adjustment")
    expected_adjustment = expected.get("structured_adjustment")

    if expected_adjustment is None:
        if actual_adjustment is not None:
            problems.append("structured_adjustment should be null")
        return problems
    if actual_adjustment is None:
        problems.append("structured_adjustment is null but a value was expected")
        return problems

    if list(actual_adjustment.get("hours", [])) != list(expected_adjustment.get("hours", [])):
        problems.append(
            f"hours {actual_adjustment.get('hours')} != {expected_adjustment.get('hours')}"
        )

    for numeric_field in ("factor", "minimum_energy_kwh", "max_grid_kwh"):
        if numeric_field not in expected_adjustment:
            continue
        expected_value = expected_adjustment[numeric_field]
        actual_value = actual_adjustment.get(numeric_field)
        if actual_value is None:
            problems.append(f"{numeric_field} is missing")
        elif not _close(float(actual_value), float(expected_value), tolerance):
            problems.append(f"{numeric_field} {actual_value} != {expected_value}")

    return problems


def _close(left: float, right: float, tolerance: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=tolerance)


__all__ = [
    "NUMERIC_TOLERANCE",
    "InterpretationComparison",
    "InterpretationDiff",
    "compare_interpretations",
]
