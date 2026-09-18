"""Independent replay of a returned schedule — the service's own judge.

This module deliberately duplicates logic that the optimizer also implements, and that
duplication is the point. If the replay validator reused the optimizer's directive compiler
or its constraint model, a bug in either would be invisible: the same wrong constraint would
build the plan and then approve it. Replay therefore derives the per-hour constraint envelope
from the directives itself, walks the plan hour by hour, and re-derives every quantity from
the response values alone.

**Do not "DRY up" this module against ``app.optimizer``.** The independence is enforced by a
test. If the two ever disagree, that is a real defect being caught, not duplication to remove.

A failure here is an application invariant failure: the plan must not be returned with HTTP 200,
and the LLM must not be retried because of it (Guide §15).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.config import Settings, SolarOverlapPolicy, get_settings
from app.schemas.directive import DirectiveInterpretation
from app.schemas.request import HOURS_IN_DAY, OptimizeRequest
from app.schemas.response import HourPlan, OptimizeResponse
from app.validation.totals import PlanTotals, recalculate_totals


class ViolationCode(StrEnum):
    """Stable identifiers for failures, so callers and tests never match on prose."""

    PLAN_HOURS_INVALID = "plan_hours_invalid"
    SCENARIO_ID_MISMATCH = "scenario_id_mismatch"
    INTERPRETATION_COUNT = "interpretation_count"
    NON_FINITE_VALUE = "non_finite_value"
    NEGATIVE_VALUE = "negative_value"
    IDLE_MAGNITUDE = "idle_magnitude"
    STATE_TRANSITION = "state_transition"
    BATTERY_BELOW_MINIMUM = "battery_below_minimum"
    BATTERY_ABOVE_CAPACITY = "battery_above_capacity"
    CHARGE_RATE_EXCEEDED = "charge_rate_exceeded"
    DISCHARGE_RATE_EXCEEDED = "discharge_rate_exceeded"
    SOLAR_OVERUSE = "solar_overuse"
    GRID_CAP_EXCEEDED = "grid_cap_exceeded"
    CHARGE_DURING_BAN = "charge_during_ban"
    DISCHARGE_DURING_BAN = "discharge_during_ban"
    ENERGY_BALANCE = "energy_balance"
    FINAL_ENERGY_NOT_NEUTRAL = "final_energy_not_neutral"
    TOTAL_GRID_MISMATCH = "total_grid_mismatch"
    TOTAL_COST_MISMATCH = "total_cost_mismatch"
    PEAK_GRID_MISMATCH = "peak_grid_mismatch"
    ENVELOPE_INFEASIBLE = "envelope_infeasible"


@dataclass(frozen=True)
class Violation:
    code: ViolationCode
    message: str
    hour: int | None = None

    def __str__(self) -> str:
        if self.hour is None:
            return f"[{self.code}] {self.message}"
        return f"[{self.code}] hour {self.hour}: {self.message}"


@dataclass
class ValidationReport:
    """The outcome of one replay. ``ok`` is the only thing the service is allowed to act on."""

    ok: bool = True
    violations: list[Violation] = field(default_factory=list)
    max_balance_error: float = 0.0
    max_state_error: float = 0.0
    final_energy_error: float = 0.0
    recalculated_total_grid_kwh: float = 0.0
    recalculated_total_cost_bdt: float = 0.0
    recalculated_peak_grid_kwh: float = 0.0

    @property
    def codes(self) -> list[ViolationCode]:
        return [violation.code for violation in self.violations]

    @property
    def messages(self) -> list[str]:
        return [str(violation) for violation in self.violations]

    def record(self, code: ViolationCode, message: str, hour: int | None = None) -> None:
        self.ok = False
        self.violations.append(Violation(code=code, message=message, hour=hour))


@dataclass(frozen=True)
class ConstraintEnvelope:
    """Per-hour limits implied by the battery plus every applicable directive.

    Derived here independently of ``app.optimizer.compile_directives``; see the module docstring.
    """

    effective_solar: tuple[float, ...]
    min_energy: tuple[float, ...]
    charge_allowed: tuple[bool, ...]
    discharge_allowed: tuple[bool, ...]
    grid_upper: tuple[float, ...]


def derive_envelope(
    request: OptimizeRequest,
    directives: Sequence[DirectiveInterpretation],
    settings: Settings | None = None,
) -> ConstraintEnvelope:
    """Build the constraint envelope straight from the validated directives.

    Composition follows the Problem Statement §5.3: reserves combine with pointwise ``max``,
    grid caps with pointwise ``min``, and charge/discharge bans are hard booleans. Two
    differing solar factors on the same hour are a specification gap, resolved by the
    configured provisional policy.
    """
    settings = settings or get_settings()
    hours = request.canonical_hours()
    battery = request.battery

    effective_solar = [entry.solar_kwh for entry in hours]
    min_energy = [battery.minimum_energy_kwh] * HOURS_IN_DAY
    charge_allowed = [True] * HOURS_IN_DAY
    discharge_allowed = [True] * HOURS_IN_DAY
    grid_upper = [math.inf] * HOURS_IN_DAY
    solar_factor: list[float | None] = [None] * HOURS_IN_DAY

    for directive in directives:
        if not directive.applies or directive.structured_adjustment is None:
            continue
        adjustment = directive.structured_adjustment

        if directive.directive_type == "solar_reduction":
            for hour in adjustment.hours:
                solar_factor[hour] = _compose_solar_factor(
                    solar_factor[hour], adjustment.factor, settings
                )
        elif directive.directive_type == "minimum_battery_reserve":
            for hour in adjustment.hours:
                min_energy[hour] = max(min_energy[hour], adjustment.minimum_energy_kwh)
        elif directive.directive_type == "no_charge_window":
            for hour in adjustment.hours:
                charge_allowed[hour] = False
        elif directive.directive_type == "no_discharge_window":
            for hour in adjustment.hours:
                discharge_allowed[hour] = False
        elif directive.directive_type == "max_grid_window":
            for hour in adjustment.hours:
                grid_upper[hour] = min(grid_upper[hour], adjustment.max_grid_kwh)

    for hour, factor in enumerate(solar_factor):
        if factor is not None:
            effective_solar[hour] = hours[hour].solar_kwh * factor

    return ConstraintEnvelope(
        effective_solar=tuple(effective_solar),
        min_energy=tuple(min_energy),
        charge_allowed=tuple(charge_allowed),
        discharge_allowed=tuple(discharge_allowed),
        grid_upper=tuple(grid_upper),
    )


def _compose_solar_factor(existing: float | None, incoming: float, settings: Settings) -> float:
    """Combine two solar factors on the same hour under the configured provisional policy."""
    if existing is None:
        return incoming
    if math.isclose(existing, incoming, rel_tol=0.0, abs_tol=1e-12):
        return existing
    if settings.solar_overlap_policy is SolarOverlapPolicy.MULTIPLY:
        return existing * incoming
    if settings.solar_overlap_policy is SolarOverlapPolicy.LAST_WINS:
        return incoming
    # Default provisional policy: never assume more solar than either directive allows.
    return min(existing, incoming)


def replay(
    request: OptimizeRequest,
    directives: Sequence[DirectiveInterpretation],
    response: OptimizeResponse,
    *,
    settings: Settings | None = None,
    tolerance: float | None = None,
) -> ValidationReport:
    """Replay ``response`` against ``request`` and ``directives``.

    The response values are the only input: nothing is read back from the solver. That is what
    makes this a check on what will actually be sent over the wire.
    """
    settings = settings or get_settings()
    tolerance = settings.internal_tolerance if tolerance is None else tolerance
    report = ValidationReport()

    if not _plan_shape_is_valid(response.hourly_plan, report):
        # Without 24 canonical hours nothing below can be evaluated meaningfully.
        return report

    if response.scenario_id != request.scenario_id:
        report.record(
            ViolationCode.SCENARIO_ID_MISMATCH,
            f"response scenario_id {response.scenario_id!r} does not echo request {request.scenario_id!r}",
        )
    if len(response.directive_interpretation) != len(request.operator_notes):
        report.record(
            ViolationCode.INTERPRETATION_COUNT,
            f"expected one interpretation per note ({len(request.operator_notes)}), "
            f"got {len(response.directive_interpretation)}",
        )

    envelope = derive_envelope(request, directives, settings)
    _check_envelope_feasibility(request, envelope, report)

    hours = request.canonical_hours()
    plan = sorted(response.hourly_plan, key=lambda entry: entry.hour)
    battery = request.battery
    energy_before = battery.initial_energy_kwh

    for entry, hour_input in zip(plan, hours, strict=True):
        hour = entry.hour
        charge, discharge = _split_action(entry, report, tolerance)

        # --- battery state -------------------------------------------------------
        expected_after = energy_before + charge - discharge
        state_error = abs(expected_after - entry.battery_energy_after_kwh)
        report.max_state_error = max(report.max_state_error, state_error)
        if state_error > tolerance:
            report.record(
                ViolationCode.STATE_TRANSITION,
                f"battery_energy_after_kwh {entry.battery_energy_after_kwh} does not follow "
                f"from {energy_before} with action {entry.battery_action} {entry.battery_kwh}",
                hour,
            )

        if entry.battery_energy_after_kwh < envelope.min_energy[hour] - tolerance:
            report.record(
                ViolationCode.BATTERY_BELOW_MINIMUM,
                f"battery energy {entry.battery_energy_after_kwh} is below the active minimum "
                f"{envelope.min_energy[hour]}",
                hour,
            )
        if entry.battery_energy_after_kwh > battery.capacity_kwh + tolerance:
            report.record(
                ViolationCode.BATTERY_ABOVE_CAPACITY,
                f"battery energy {entry.battery_energy_after_kwh} exceeds capacity {battery.capacity_kwh}",
                hour,
            )

        # --- rate limits and directive bans --------------------------------------
        if charge > battery.max_charge_kwh_per_hour + tolerance:
            report.record(
                ViolationCode.CHARGE_RATE_EXCEEDED,
                f"charge {charge} exceeds max_charge_kwh_per_hour {battery.max_charge_kwh_per_hour}",
                hour,
            )
        if discharge > battery.max_discharge_kwh_per_hour + tolerance:
            report.record(
                ViolationCode.DISCHARGE_RATE_EXCEEDED,
                f"discharge {discharge} exceeds max_discharge_kwh_per_hour "
                f"{battery.max_discharge_kwh_per_hour}",
                hour,
            )
        if not envelope.charge_allowed[hour] and charge > tolerance:
            report.record(
                ViolationCode.CHARGE_DURING_BAN,
                f"charged {charge} during a no_charge_window hour",
                hour,
            )
        if not envelope.discharge_allowed[hour] and discharge > tolerance:
            report.record(
                ViolationCode.DISCHARGE_DURING_BAN,
                f"discharged {discharge} during a no_discharge_window hour",
                hour,
            )

        # --- solar and grid ------------------------------------------------------
        if entry.solar_used_kwh > envelope.effective_solar[hour] + tolerance:
            report.record(
                ViolationCode.SOLAR_OVERUSE,
                f"solar_used_kwh {entry.solar_used_kwh} exceeds effective solar "
                f"{envelope.effective_solar[hour]}",
                hour,
            )
        if entry.grid_kwh > envelope.grid_upper[hour] + tolerance:
            report.record(
                ViolationCode.GRID_CAP_EXCEEDED,
                f"grid_kwh {entry.grid_kwh} exceeds the directive cap {envelope.grid_upper[hour]}",
                hour,
            )

        # --- energy balance ------------------------------------------------------
        supply = entry.grid_kwh + entry.solar_used_kwh + discharge
        demand = hour_input.demand_kwh + charge
        balance_error = abs(supply - demand)
        report.max_balance_error = max(report.max_balance_error, balance_error)
        if balance_error > tolerance:
            report.record(
                ViolationCode.ENERGY_BALANCE,
                f"grid+solar+discharge ({supply}) != demand+charge ({demand})",
                hour,
            )

        # The reported state is carried forward, so one bad hour does not cascade into
        # 23 further transition errors.
        energy_before = entry.battery_energy_after_kwh

    report.final_energy_error = abs(energy_before - battery.initial_energy_kwh)
    if report.final_energy_error > tolerance:
        report.record(
            ViolationCode.FINAL_ENERGY_NOT_NEUTRAL,
            f"final battery energy {energy_before} does not equal initial "
            f"{battery.initial_energy_kwh}",
        )

    _check_totals(request, response, report, tolerance)
    return report


def _plan_shape_is_valid(plan: Sequence[HourPlan], report: ValidationReport) -> bool:
    hour_ids = [entry.hour for entry in plan]
    if len(plan) != HOURS_IN_DAY or sorted(hour_ids) != list(range(HOURS_IN_DAY)):
        report.record(
            ViolationCode.PLAN_HOURS_INVALID,
            "hourly_plan must contain exactly one entry for each hour 0 through 23",
        )
        return False
    return True


def _split_action(entry: HourPlan, report: ValidationReport, tolerance: float) -> tuple[float, float]:
    """Turn the declared action plus magnitude into (charge, discharge)."""
    for name, value in (
        ("grid_kwh", entry.grid_kwh),
        ("solar_used_kwh", entry.solar_used_kwh),
        ("battery_kwh", entry.battery_kwh),
        ("battery_energy_after_kwh", entry.battery_energy_after_kwh),
    ):
        if not math.isfinite(value):
            report.record(ViolationCode.NON_FINITE_VALUE, f"{name} is not a finite number", entry.hour)
        elif value < 0:
            report.record(ViolationCode.NEGATIVE_VALUE, f"{name} is negative ({value})", entry.hour)

    if entry.battery_action == "charge":
        return entry.battery_kwh, 0.0
    if entry.battery_action == "discharge":
        return 0.0, entry.battery_kwh
    if abs(entry.battery_kwh) > tolerance:
        report.record(
            ViolationCode.IDLE_MAGNITUDE,
            f"battery_kwh must be 0 when idle, got {entry.battery_kwh}",
            entry.hour,
        )
    return 0.0, 0.0


def _check_envelope_feasibility(
    request: OptimizeRequest, envelope: ConstraintEnvelope, report: ValidationReport
) -> None:
    """A reserve floor above capacity can never be satisfied; say so plainly."""
    for hour, minimum in enumerate(envelope.min_energy):
        if minimum > request.battery.capacity_kwh:
            report.record(
                ViolationCode.ENVELOPE_INFEASIBLE,
                f"active minimum energy {minimum} exceeds battery capacity {request.battery.capacity_kwh}",
                hour,
            )


def _check_totals(
    request: OptimizeRequest,
    response: OptimizeResponse,
    report: ValidationReport,
    tolerance: float,
) -> None:
    tariff_by_hour = {entry.hour: entry.tariff_bdt_per_kwh for entry in request.canonical_hours()}
    totals: PlanTotals = recalculate_totals(response.hourly_plan, tariff_by_hour)

    report.recalculated_total_grid_kwh = totals.total_grid_kwh
    report.recalculated_total_cost_bdt = totals.total_cost_bdt
    report.recalculated_peak_grid_kwh = totals.peak_grid_kwh

    for code, reported, recalculated, label in (
        (ViolationCode.TOTAL_GRID_MISMATCH, response.total_grid_kwh, totals.total_grid_kwh, "total_grid_kwh"),
        (ViolationCode.TOTAL_COST_MISMATCH, response.total_cost_bdt, totals.total_cost_bdt, "total_cost_bdt"),
        (ViolationCode.PEAK_GRID_MISMATCH, response.peak_grid_kwh, totals.peak_grid_kwh, "peak_grid_kwh"),
    ):
        if abs(reported - recalculated) > tolerance:
            report.record(code, f"reported {label} {reported} != recalculated {recalculated}")


__all__ = [
    "ConstraintEnvelope",
    "ValidationReport",
    "Violation",
    "ViolationCode",
    "derive_envelope",
    "replay",
]
