"""The deterministic boundary between model output and the optimizer.

Everything upstream is probabilistic; everything downstream treats directives as facts. This
module is where that changes, so it is written to a simple rule: **a schema-valid object is not
a correct one.** The provider's structured output guarantees shape at best; whether the hours
are unique, the reserve fits inside the battery, and every note got exactly one entry is decided
here, on the raw payload, before any Pydantic model exists.

Two properties matter for the phases around it:

* **Failures are classified, not lumped together.** Each carries a stable
  :class:`GuardrailCode`, because P10 routes a duplicate hour to a bounded repair and a
  reserve-above-capacity to a focused semantic retry, and those are different prompts.
* **All failures are collected, not just the first.** A repair request that lists every problem
  has a far better chance of being fixed in one attempt than one that reveals them one at a time.

Checks run on the raw dictionaries rather than on parsed models on purpose: Pydantic would
reject an unknown directive type and a duplicate hour with the same opaque error, and the
distinction between them is exactly what this layer exists to preserve.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.config import Settings, get_settings
from app.guardrails.normalizer import (
    normalize_explanation,
    normalize_negative_zero,
    sort_entries_by_note_index,
    sort_hours,
)
from app.llm.base import MalformedModelOutput
from app.llm.interpreter import coerce_to_canonical
from app.schemas.directive import DIRECTIVE_TYPE_VALUES, DirectiveInterpretation, DirectiveType
from app.schemas.request import HOURS_IN_DAY, OptimizeRequest

REQUIRED_ENTRY_FIELDS = ("note_index", "applies", "directive_type", "structured_adjustment", "explanation")

#: Exact adjustment keys each directive type must carry — no more, no fewer.
ADJUSTMENT_FIELDS: dict[str, frozenset[str]] = {
    DirectiveType.SOLAR_REDUCTION.value: frozenset({"hours", "factor"}),
    DirectiveType.MINIMUM_BATTERY_RESERVE.value: frozenset({"hours", "minimum_energy_kwh"}),
    DirectiveType.NO_CHARGE_WINDOW.value: frozenset({"hours"}),
    DirectiveType.NO_DISCHARGE_WINDOW.value: frozenset({"hours"}),
    DirectiveType.MAX_GRID_WINDOW.value: frozenset({"hours", "max_grid_kwh"}),
}


class GuardrailCode(StrEnum):
    """Stable failure classes. P10's repair policy branches on these."""

    NOT_AN_OBJECT = "not_an_object"
    WRONG_ENTRY_COUNT = "wrong_entry_count"
    MISSING_FIELD = "missing_field"
    NOTE_INDEX_NOT_INTEGER = "note_index_not_integer"
    NOTE_INDEX_OUT_OF_RANGE = "note_index_out_of_range"
    DUPLICATE_NOTE_INDEX = "duplicate_note_index"
    MISSING_NOTE_INDEX = "missing_note_index"
    UNKNOWN_DIRECTIVE_TYPE = "unknown_directive_type"
    APPLIES_NOT_BOOLEAN = "applies_not_boolean"
    APPLIES_MISMATCH = "applies_mismatch"
    NO_OP_WITH_ADJUSTMENT = "no_op_with_adjustment"
    ADJUSTMENT_MISSING = "adjustment_missing"
    ADJUSTMENT_SHAPE = "adjustment_shape"
    HOURS_NOT_A_LIST = "hours_not_a_list"
    HOURS_EMPTY = "hours_empty"
    HOUR_NOT_INTEGER = "hour_not_integer"
    HOUR_OUT_OF_RANGE = "hour_out_of_range"
    DUPLICATE_HOURS = "duplicate_hours"
    FACTOR_NOT_A_NUMBER = "factor_not_a_number"
    FACTOR_OUT_OF_RANGE = "factor_out_of_range"
    RESERVE_NOT_A_NUMBER = "reserve_not_a_number"
    RESERVE_NEGATIVE = "reserve_negative"
    RESERVE_ABOVE_CAPACITY = "reserve_above_capacity"
    GRID_CAP_NOT_A_NUMBER = "grid_cap_not_a_number"
    GRID_CAP_NEGATIVE = "grid_cap_negative"
    SCHEMA_BACKSTOP = "schema_backstop"


@dataclass(frozen=True)
class GuardrailFailure:
    code: GuardrailCode
    message: str
    note_index: int | None = None

    def __str__(self) -> str:
        if self.note_index is None:
            return f"[{self.code}] {self.message}"
        return f"[{self.code}] note {self.note_index}: {self.message}"


@dataclass
class GuardrailReport:
    """Outcome of validating one model response."""

    ok: bool = True
    directives: list[DirectiveInterpretation] = field(default_factory=list)
    failures: list[GuardrailFailure] = field(default_factory=list)
    #: Safe normalizations that were applied, for telemetry and the demo trace.
    normalizations: list[str] = field(default_factory=list)

    @property
    def codes(self) -> list[GuardrailCode]:
        return [failure.code for failure in self.failures]

    @property
    def messages(self) -> list[str]:
        return [str(failure) for failure in self.failures]

    def record(self, code: GuardrailCode, message: str, note_index: int | None = None) -> None:
        self.ok = False
        self.failures.append(GuardrailFailure(code=code, message=message, note_index=note_index))


def validate_directives(
    raw_items: Sequence[Any],
    request: OptimizeRequest,
    settings: Settings | None = None,
) -> GuardrailReport:
    """Validate raw model output against the canonical rules for this scenario.

    Returns a report rather than raising: the caller decides whether to repair (P10) or fail.
    """
    settings = settings or get_settings()
    report = GuardrailReport()
    note_count = len(request.operator_notes)

    items = list(raw_items)
    for position, item in enumerate(items):
        if not isinstance(item, dict):
            report.record(
                GuardrailCode.NOT_AN_OBJECT,
                f"entry at position {position} is {type(item).__name__}, expected an object",
            )
    if not report.ok:
        return report

    if len(items) != note_count:
        report.record(
            GuardrailCode.WRONG_ENTRY_COUNT,
            f"expected exactly one entry per operator note ({note_count}), got {len(items)}",
        )

    ordered, reordered = sort_entries_by_note_index(items)
    if reordered:
        report.normalizations.append("sorted entries by note_index")

    _check_note_index_coverage(ordered, note_count, report)

    cleaned: list[dict[str, Any]] = []
    for position, item in enumerate(ordered):
        cleaned.append(_validate_entry(item, position, request, report))

    if not report.ok:
        return report

    # Backstop: the canonical models must also accept the cleaned payload. If they do not, a
    # check above is missing, and failing closed is better than emitting an unvalidated plan.
    try:
        report.directives = coerce_to_canonical(cleaned)
    except MalformedModelOutput as exc:
        report.record(
            GuardrailCode.SCHEMA_BACKSTOP,
            f"cleaned output still failed the canonical schema: {'; '.join(exc.problems) or exc}",
        )
    return report


def _check_note_index_coverage(
    items: list[dict[str, Any]], note_count: int, report: GuardrailReport
) -> None:
    """Every note must be interpreted exactly once (Problem Statement §05.1)."""
    seen: set[int] = set()
    for position, item in enumerate(items):
        index = item.get("note_index")
        if not _is_integer(index):
            report.record(
                GuardrailCode.NOTE_INDEX_NOT_INTEGER,
                f"note_index {index!r} at position {position} is not an integer",
            )
            continue
        if not 0 <= index < note_count:
            report.record(
                GuardrailCode.NOTE_INDEX_OUT_OF_RANGE,
                f"note_index {index} is outside 0..{note_count - 1}",
            )
            continue
        if index in seen:
            report.record(GuardrailCode.DUPLICATE_NOTE_INDEX, f"note_index {index} appears twice")
        seen.add(index)

    missing = sorted(set(range(note_count)) - seen)
    if missing:
        report.record(
            GuardrailCode.MISSING_NOTE_INDEX,
            f"no interpretation returned for note(s) {missing}",
        )


def _validate_entry(
    item: dict[str, Any],
    position: int,
    request: OptimizeRequest,
    report: GuardrailReport,
) -> dict[str, Any]:
    """Validate one entry and return its normalized copy."""
    entry = dict(item)
    note_index = entry.get("note_index")
    label = note_index if _is_integer(note_index) else position

    for required in REQUIRED_ENTRY_FIELDS:
        if required not in entry:
            # explanation is free text with no score attached; a missing one is filled in
            # rather than costing the case a repair round trip.
            if required == "explanation":
                continue
            report.record(GuardrailCode.MISSING_FIELD, f"missing {required!r}", label)

    explanation, changed = normalize_explanation(entry.get("explanation"))
    entry["explanation"] = explanation
    if changed:
        report.normalizations.append(f"note {label}: normalized explanation")

    directive_type = entry.get("directive_type")
    if directive_type not in DIRECTIVE_TYPE_VALUES:
        # Never coerced to something familiar: an unknown type means the note was not understood.
        report.record(
            GuardrailCode.UNKNOWN_DIRECTIVE_TYPE,
            f"{directive_type!r} is not one of the six supported directive types",
            label,
        )
        return entry

    applies = entry.get("applies")
    if not isinstance(applies, bool):
        report.record(GuardrailCode.APPLIES_NOT_BOOLEAN, f"applies {applies!r} is not a boolean", label)
    else:
        expected_applies = directive_type != DirectiveType.NO_OP.value
        if applies is not expected_applies:
            report.record(
                GuardrailCode.APPLIES_MISMATCH,
                f"{directive_type} requires applies={expected_applies}, got {applies}",
                label,
            )

    adjustment = entry.get("structured_adjustment")
    if directive_type == DirectiveType.NO_OP.value:
        if adjustment is not None:
            report.record(
                GuardrailCode.NO_OP_WITH_ADJUSTMENT,
                "no_op must carry structured_adjustment=null",
                label,
            )
        return entry

    if adjustment is None:
        report.record(GuardrailCode.ADJUSTMENT_MISSING, f"{directive_type} requires an adjustment", label)
        return entry
    if not isinstance(adjustment, dict):
        report.record(
            GuardrailCode.ADJUSTMENT_SHAPE,
            f"structured_adjustment is {type(adjustment).__name__}, expected an object",
            label,
        )
        return entry

    adjustment = dict(adjustment)
    entry["structured_adjustment"] = adjustment

    expected_fields = ADJUSTMENT_FIELDS[directive_type]
    present = set(adjustment)
    if present != expected_fields:
        missing = sorted(expected_fields - present)
        unexpected = sorted(present - expected_fields)
        report.record(
            GuardrailCode.ADJUSTMENT_SHAPE,
            f"{directive_type} adjustment must have exactly {sorted(expected_fields)}"
            + (f"; missing {missing}" if missing else "")
            + (f"; unexpected {unexpected}" if unexpected else ""),
            label,
        )

    if "hours" in adjustment:
        _validate_hours(adjustment, label, report)
    if directive_type == DirectiveType.SOLAR_REDUCTION.value and "factor" in adjustment:
        _validate_factor(adjustment, label, report)
    if directive_type == DirectiveType.MINIMUM_BATTERY_RESERVE.value and "minimum_energy_kwh" in adjustment:
        _validate_reserve(adjustment, label, request, report)
    if directive_type == DirectiveType.MAX_GRID_WINDOW.value and "max_grid_kwh" in adjustment:
        _validate_grid_cap(adjustment, label, report)

    return entry


def _validate_hours(adjustment: dict[str, Any], label: int, report: GuardrailReport) -> None:
    hours = adjustment.get("hours")
    if not isinstance(hours, list):
        report.record(
            GuardrailCode.HOURS_NOT_A_LIST,
            f"hours is {type(hours).__name__}, expected a list",
            label,
        )
        return
    if not hours:
        report.record(
            GuardrailCode.HOURS_EMPTY,
            "hours is empty; a window must affect at least one hour",
            label,
        )
        return

    non_integers = [hour for hour in hours if not _is_integer(hour)]
    if non_integers:
        report.record(GuardrailCode.HOUR_NOT_INTEGER, f"non-integer hour(s) {non_integers!r}", label)
        return

    out_of_range = [hour for hour in hours if not 0 <= hour <= HOURS_IN_DAY - 1]
    if out_of_range:
        # Never clipped into range: an out-of-range hour means the window was misread.
        report.record(GuardrailCode.HOUR_OUT_OF_RANGE, f"hour(s) {out_of_range} outside 0..23", label)

    if len(set(hours)) != len(hours):
        # Never deduplicated. Uniqueness is a published, machine-checkable requirement, and a
        # repeated hour suggests the extraction went wrong rather than that it needs tidying.
        duplicates = sorted({hour for hour in hours if hours.count(hour) > 1})
        report.record(GuardrailCode.DUPLICATE_HOURS, f"duplicate hour(s) {duplicates}", label)
        return

    ordered, changed = sort_hours(hours)
    if changed:
        # Safe: a window is a set, so ordering carries no meaning, and ascending is the
        # canonical form the response contract requires.
        adjustment["hours"] = ordered
        report.normalizations.append(f"note {label}: sorted hours")


def _validate_factor(adjustment: dict[str, Any], label: int, report: GuardrailReport) -> None:
    factor = adjustment.get("factor")
    if not _is_finite_number(factor):
        report.record(GuardrailCode.FACTOR_NOT_A_NUMBER, f"factor {factor!r} is not a finite number", label)
        return
    if not 0.0 <= factor <= 1.0:
        # Never clipped: a factor of 1.8 means the model misread the note, and clamping to 1.0
        # would turn a detectable error into a silently wrong constraint.
        report.record(GuardrailCode.FACTOR_OUT_OF_RANGE, f"factor {factor} is outside [0, 1]", label)
        return
    adjustment["factor"] = normalize_negative_zero(float(factor))


def _validate_reserve(
    adjustment: dict[str, Any], label: int, request: OptimizeRequest, report: GuardrailReport
) -> None:
    reserve = adjustment.get("minimum_energy_kwh")
    if not _is_finite_number(reserve):
        report.record(
            GuardrailCode.RESERVE_NOT_A_NUMBER,
            f"minimum_energy_kwh {reserve!r} is not a finite number",
            label,
        )
        return
    if reserve < 0:
        report.record(GuardrailCode.RESERVE_NEGATIVE, f"minimum_energy_kwh {reserve} is negative", label)
        return
    capacity = request.battery.capacity_kwh
    if reserve > capacity:
        # Scenario-dependent, which is why it cannot live in the schema: the same number is
        # valid for one battery and impossible for another.
        report.record(
            GuardrailCode.RESERVE_ABOVE_CAPACITY,
            f"minimum_energy_kwh {reserve} exceeds battery capacity {capacity}",
            label,
        )
        return
    adjustment["minimum_energy_kwh"] = normalize_negative_zero(float(reserve))


def _validate_grid_cap(adjustment: dict[str, Any], label: int, report: GuardrailReport) -> None:
    cap = adjustment.get("max_grid_kwh")
    if not _is_finite_number(cap):
        report.record(
            GuardrailCode.GRID_CAP_NOT_A_NUMBER,
            f"max_grid_kwh {cap!r} is not a finite number",
            label,
        )
        return
    if cap < 0:
        report.record(GuardrailCode.GRID_CAP_NEGATIVE, f"max_grid_kwh {cap} is negative", label)
        return
    # Zero is a real ceiling ("no grid import"), so this must never be a truthiness check.
    adjustment["max_grid_kwh"] = normalize_negative_zero(float(cap))


def _is_integer(value: Any) -> bool:
    # bool is a subclass of int; True is not an hour.
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return math.isfinite(value)


__all__ = [
    "ADJUSTMENT_FIELDS",
    "REQUIRED_ENTRY_FIELDS",
    "GuardrailCode",
    "GuardrailFailure",
    "GuardrailReport",
    "validate_directives",
]
