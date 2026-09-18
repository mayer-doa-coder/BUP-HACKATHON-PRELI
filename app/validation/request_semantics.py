"""Domain-sanity checks for a structurally valid request.

A request that reaches this module already has the right shape. What is checked here is
whether the *scenario* makes physical sense — a battery that starts above its own capacity,
a reserve floor above capacity, negative energy. Those are semantic failures (HTTP 422),
not malformed requests (HTTP 400), which is why they are deliberately kept out of the
Pydantic models.

Two things are intentionally **not** checked:

* Tariff sign. The canonical request schema defines tariff as a number and never requires it
  to be non-negative, so a negative tariff is accepted rather than rejected on an invented rule.
* Feasibility. Whether the scenario can actually be scheduled is decided by the baseline
  feasibility LP (P5), not by hand-written rules here.
"""

from __future__ import annotations

from app.config import Settings
from app.schemas.request import OptimizeRequest

# Only the first few offending hours are reported; the message is for the caller, not a dump.
MAX_REPORTED_HOURS = 3


def check_request_semantics(request: OptimizeRequest, settings: Settings) -> list[str]:
    """Return a list of semantic violations. An empty list means the scenario is sane."""
    violations: list[str] = []
    battery = request.battery

    if battery.capacity_kwh < 0:
        violations.append("battery.capacity_kwh must not be negative")
    if battery.max_charge_kwh_per_hour < 0:
        violations.append("battery.max_charge_kwh_per_hour must not be negative")
    if battery.max_discharge_kwh_per_hour < 0:
        violations.append("battery.max_discharge_kwh_per_hour must not be negative")

    if battery.initial_energy_kwh < 0:
        violations.append("battery.initial_energy_kwh must not be negative")
    elif battery.initial_energy_kwh > battery.capacity_kwh:
        violations.append("battery.initial_energy_kwh must not exceed battery.capacity_kwh")

    if battery.minimum_energy_kwh < 0:
        violations.append("battery.minimum_energy_kwh must not be negative")
    elif battery.minimum_energy_kwh > battery.capacity_kwh:
        violations.append("battery.minimum_energy_kwh must not exceed battery.capacity_kwh")

    if settings.reject_negative_energy_inputs:
        violations.extend(_negative_energy_violations(request))

    return violations


def _negative_energy_violations(request: OptimizeRequest) -> list[str]:
    negative_demand = [entry.hour for entry in request.canonical_hours() if entry.demand_kwh < 0]
    negative_solar = [entry.hour for entry in request.canonical_hours() if entry.solar_kwh < 0]

    violations: list[str] = []
    if negative_demand:
        violations.append(f"demand_kwh must not be negative (hours {_summarize(negative_demand)})")
    if negative_solar:
        violations.append(f"solar_kwh must not be negative (hours {_summarize(negative_solar)})")
    return violations


def _summarize(hours: list[int]) -> str:
    head = ", ".join(str(hour) for hour in hours[:MAX_REPORTED_HOURS])
    remaining = len(hours) - MAX_REPORTED_HOURS
    return f"{head}, +{remaining} more" if remaining > 0 else head


def check_note_length_limits(request: OptimizeRequest, settings: Settings) -> list[str]:
    """Return violations for operator notes longer than the configured protection limit.

    This is an engineering resource protection, not an organizer rule, so the limit is
    generous and configurable. Oversized input maps to the configured status (413 by default).
    """
    return [
        f"operator_notes[{index}] exceeds the {settings.max_note_chars} character limit"
        for index, note in enumerate(request.operator_notes)
        if len(note) > settings.max_note_chars
    ]


__all__ = ["check_note_length_limits", "check_request_semantics"]
