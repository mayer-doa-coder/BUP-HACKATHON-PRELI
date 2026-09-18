"""The closed directive taxonomy, modelled as a discriminated union.

These are the **canonical** directive models: what the service returns in
``directive_interpretation`` and what the optimizer compiles. A discriminated union makes
impossible field combinations unrepresentable — there is no way to build a ``no_op`` that
carries an adjustment, or a ``solar_reduction`` with ``applies=false``.

Raw LLM output is *not* parsed straight into these models. It is parsed permissively and
then checked by the deterministic guardrails (P9), which classify each failure so a
duplicate hour triggers the bounded repair path instead of a generic parse error. These
models are the guardrail's output type, not its input.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator

from app.schemas.request import HOURS_IN_DAY, StrictModel


class DirectiveType(StrEnum):
    """The complete taxonomy. Nothing outside this set may ever reach the optimizer."""

    SOLAR_REDUCTION = "solar_reduction"
    MINIMUM_BATTERY_RESERVE = "minimum_battery_reserve"
    NO_CHARGE_WINDOW = "no_charge_window"
    NO_DISCHARGE_WINDOW = "no_discharge_window"
    MAX_GRID_WINDOW = "max_grid_window"
    NO_OP = "no_op"


DIRECTIVE_TYPE_VALUES: frozenset[str] = frozenset(member.value for member in DirectiveType)
ACTIONABLE_DIRECTIVE_TYPES: frozenset[str] = DIRECTIVE_TYPE_VALUES - {DirectiveType.NO_OP.value}


class HourSetAdjustment(StrictModel):
    """Base shape for every adjustment: the affected hours.

    Hours are unique integers 0-23 in ascending order (Problem Statement §05.1). An empty
    hour set is rejected: a window that affects no hour is an extraction failure, not a
    directive, and must fail closed rather than compile into a no-op constraint.
    """

    hours: list[int] = Field(min_length=1, max_length=HOURS_IN_DAY)

    @field_validator("hours")
    @classmethod
    def _hours_are_unique_ascending_and_in_range(cls, hours: list[int]) -> list[int]:
        for hour in hours:
            if not 0 <= hour <= HOURS_IN_DAY - 1:
                raise ValueError(f"hour {hour} is outside 0..23")
        if len(set(hours)) != len(hours):
            raise ValueError("hours must be unique")
        if hours != sorted(hours):
            raise ValueError("hours must be in ascending order")
        return hours


class SolarAdjustment(HourSetAdjustment):
    """``factor`` is the usable fraction of solar that *remains*, not the amount removed."""

    factor: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)


class ReserveAdjustment(HourSetAdjustment):
    """Absolute reserve floor in kWh. A percentage note is resolved against battery capacity."""

    minimum_energy_kwh: float = Field(ge=0.0, allow_inf_nan=False)


class GridCapAdjustment(HourSetAdjustment):
    """Per-hour ceiling on grid import. Zero is a valid, meaningful cap."""

    max_grid_kwh: float = Field(ge=0.0, allow_inf_nan=False)


# Field order below matches Problem Statement §10.2 so the emitted JSON reads the same way
# the specification presents it.


class SolarReductionDirective(StrictModel):
    note_index: int = Field(ge=0)
    applies: Literal[True] = True
    directive_type: Literal["solar_reduction"] = "solar_reduction"
    structured_adjustment: SolarAdjustment
    explanation: str = ""


class MinimumBatteryReserveDirective(StrictModel):
    note_index: int = Field(ge=0)
    applies: Literal[True] = True
    directive_type: Literal["minimum_battery_reserve"] = "minimum_battery_reserve"
    structured_adjustment: ReserveAdjustment
    explanation: str = ""


class NoChargeWindowDirective(StrictModel):
    note_index: int = Field(ge=0)
    applies: Literal[True] = True
    directive_type: Literal["no_charge_window"] = "no_charge_window"
    structured_adjustment: HourSetAdjustment
    explanation: str = ""


class NoDischargeWindowDirective(StrictModel):
    note_index: int = Field(ge=0)
    applies: Literal[True] = True
    directive_type: Literal["no_discharge_window"] = "no_discharge_window"
    structured_adjustment: HourSetAdjustment
    explanation: str = ""


class MaxGridWindowDirective(StrictModel):
    note_index: int = Field(ge=0)
    applies: Literal[True] = True
    directive_type: Literal["max_grid_window"] = "max_grid_window"
    structured_adjustment: GridCapAdjustment
    explanation: str = ""


class NoOpDirective(StrictModel):
    """The only directive allowed to use ``applies=false``, and it must carry no adjustment."""

    note_index: int = Field(ge=0)
    applies: Literal[False] = False
    directive_type: Literal["no_op"] = "no_op"
    structured_adjustment: None = None
    explanation: str = ""


DirectiveInterpretation = Annotated[
    SolarReductionDirective
    | MinimumBatteryReserveDirective
    | NoChargeWindowDirective
    | NoDischargeWindowDirective
    | MaxGridWindowDirective
    | NoOpDirective,
    Field(discriminator="directive_type"),
]

ActionableDirective = (
    SolarReductionDirective
    | MinimumBatteryReserveDirective
    | NoChargeWindowDirective
    | NoDischargeWindowDirective
    | MaxGridWindowDirective
)


__all__ = [
    "ACTIONABLE_DIRECTIVE_TYPES",
    "DIRECTIVE_TYPE_VALUES",
    "ActionableDirective",
    "DirectiveInterpretation",
    "DirectiveType",
    "GridCapAdjustment",
    "HourSetAdjustment",
    "MaxGridWindowDirective",
    "MinimumBatteryReserveDirective",
    "NoChargeWindowDirective",
    "NoDischargeWindowDirective",
    "NoOpDirective",
    "ReserveAdjustment",
    "SolarAdjustment",
    "SolarReductionDirective",
]
