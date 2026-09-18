"""Canonical request models for ``POST /optimize-energy``.

This module owns **contract/structural** validation only — the things the Problem Statement
§07 defines as the shape of a request. Anything that fails here is a structurally invalid
request and maps to HTTP 400.

Domain-sanity checks that depend on relationships between fields (initial energy above
capacity, negative demand, ...) deliberately live in ``app.validation.request_semantics``
instead, because those are semantic failures and map to HTTP 422.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

HOURS_IN_DAY = 24
CANONICAL_HOUR_SET = frozenset(range(HOURS_IN_DAY))

MIN_OPERATOR_NOTES = 1
MAX_OPERATOR_NOTES = 3


class StrictModel(BaseModel):
    """Base model for every judge-facing schema: unknown fields are a contract violation."""

    model_config = ConfigDict(extra="forbid")


# NaN and Infinity are JSON-parseable in Python but are never valid scenario numbers.
Finite = Annotated[float, Field(allow_inf_nan=False)]


class HourInput(StrictModel):
    """One hourly record of the 24-hour scenario."""

    hour: int = Field(ge=0, le=HOURS_IN_DAY - 1)
    demand_kwh: Finite
    solar_kwh: Finite
    tariff_bdt_per_kwh: Finite


class BatteryInput(StrictModel):
    """Battery parameters for the scenario. All five fields are required."""

    capacity_kwh: Finite
    initial_energy_kwh: Finite
    minimum_energy_kwh: Finite
    max_charge_kwh_per_hour: Finite
    max_discharge_kwh_per_hour: Finite


class OptimizeRequest(StrictModel):
    """One scenario: identifier, 1-3 operator notes, 24 hourly records, and the battery."""

    scenario_id: str
    operator_notes: list[str] = Field(min_length=MIN_OPERATOR_NOTES, max_length=MAX_OPERATOR_NOTES)
    hours: list[HourInput] = Field(min_length=HOURS_IN_DAY, max_length=HOURS_IN_DAY)
    battery: BatteryInput

    @field_validator("operator_notes")
    @classmethod
    def _notes_must_carry_text(cls, notes: list[str]) -> list[str]:
        # Note text itself is left untouched — trimming here would alter what the
        # interpreter sees. This only rejects notes that are empty after trimming.
        for index, note in enumerate(notes):
            if not note.strip():
                raise ValueError(f"operator_notes[{index}] must not be empty or whitespace only")
        return notes

    @model_validator(mode="after")
    def _hour_ids_are_exactly_zero_to_23(self) -> OptimizeRequest:
        hour_ids = [entry.hour for entry in self.hours]
        if len(set(hour_ids)) != len(hour_ids):
            raise ValueError("hours must not contain duplicate hour identifiers")
        if set(hour_ids) != CANONICAL_HOUR_SET:
            raise ValueError("hours must contain exactly one entry for each hour 0 through 23")
        return self

    def canonical_hours(self) -> tuple[HourInput, ...]:
        """Hourly records ordered by the ``hour`` field.

        Array position is never trusted as the hour number (Guide §5): a request may list
        the hours in any order, and every downstream stage consumes this ordering instead.
        """
        return tuple(sorted(self.hours, key=lambda entry: entry.hour))


__all__ = [
    "CANONICAL_HOUR_SET",
    "HOURS_IN_DAY",
    "BatteryInput",
    "Finite",
    "HourInput",
    "OptimizeRequest",
    "StrictModel",
]
