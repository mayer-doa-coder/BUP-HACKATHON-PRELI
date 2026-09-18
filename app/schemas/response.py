"""The exact ``POST /optimize-energy`` success response.

Seven top-level fields, no more. ``extra="forbid"`` is what stops a debug, confidence, or
solver field from ever being added by accident.

The model validators here are a fail-closed safety net, not the real validation: the
independent replay validator (P2) is what proves a plan. If a validator here trips, the
service has produced an invalid response and must fail with a controlled 500 rather than
return it with HTTP 200.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.schemas.directive import DirectiveInterpretation
from app.schemas.request import HOURS_IN_DAY, MAX_OPERATOR_NOTES, MIN_OPERATOR_NOTES, Finite, StrictModel

# An action declared "idle" must carry a zero magnitude. The tolerance only absorbs a
# floating-point artifact; the canonicalizer emits an exact 0.0.
IDLE_MAGNITUDE_TOLERANCE = 1e-12


class HourPlan(StrictModel):
    """One hour of the returned schedule."""

    hour: int = Field(ge=0, le=HOURS_IN_DAY - 1)
    grid_kwh: float = Field(ge=0.0, allow_inf_nan=False)
    solar_used_kwh: float = Field(ge=0.0, allow_inf_nan=False)
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: float = Field(ge=0.0, allow_inf_nan=False)
    battery_energy_after_kwh: float = Field(ge=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _idle_carries_no_magnitude(self) -> HourPlan:
        if self.battery_action == "idle" and abs(self.battery_kwh) > IDLE_MAGNITUDE_TOLERANCE:
            raise ValueError(f"hour {self.hour}: battery_kwh must be 0 when battery_action is idle")
        return self


class OptimizeResponse(StrictModel):
    """The canonical response body. Nothing internal may be added to it."""

    scenario_id: str
    directive_interpretation: list[DirectiveInterpretation] = Field(
        min_length=MIN_OPERATOR_NOTES, max_length=MAX_OPERATOR_NOTES
    )
    hourly_plan: list[HourPlan] = Field(min_length=HOURS_IN_DAY, max_length=HOURS_IN_DAY)
    total_grid_kwh: Finite
    total_cost_bdt: Finite
    peak_grid_kwh: Finite
    plan_summary: str

    @model_validator(mode="after")
    def _plan_and_interpretation_are_canonically_ordered(self) -> OptimizeResponse:
        plan_hours = [entry.hour for entry in self.hourly_plan]
        if plan_hours != list(range(HOURS_IN_DAY)):
            raise ValueError("hourly_plan must contain hours 0 through 23 exactly once, in ascending order")

        note_indices = [item.note_index for item in self.directive_interpretation]
        if note_indices != list(range(len(note_indices))):
            raise ValueError("directive_interpretation must contain note_index 0..N-1 in order")
        return self


__all__ = ["IDLE_MAGNITUDE_TOLERANCE", "HourPlan", "OptimizeResponse"]
