"""Turn the authoritative MILP solution into the schedule that will actually be returned.

The dangerous step in this whole pipeline is numerical. A solver vector can be perfectly valid
while a response built by independently rounding each field is not: round ``grid``, ``solar``,
``charge`` and ``state of charge`` separately and the energy balance no longer closes.

So this module rounds only the **independent decisions** — charge, discharge and solar used —
and then *derives* everything that depends on them:

* ``battery_energy_after_kwh`` is rebuilt sequentially from the rounded battery movements,
  never read back from the solver;
* ``grid_kwh`` is recomputed from the energy balance, so the balance closes by construction.

Rounding can still nudge a value a hair past a bound it was sitting exactly on. Overshoot
within ``BOUND_REPAIR_TOLERANCE`` is clipped back, because it is a rounding artifact. Anything
larger is a real violation and fails closed — a materially invalid value is never clipped into
looking valid.
"""

from __future__ import annotations

import numpy as np
from pydantic import ValidationError

from app.api.errors import SolverFailure
from app.config import Settings, get_settings
from app.optimizer.compile_directives import CompiledConstraints
from app.optimizer.model import CHARGE, DISCHARGE, SOLAR
from app.schemas.request import HOURS_IN_DAY, OptimizeRequest
from app.schemas.response import HourPlan

# Largest bound overshoot attributable to rounding. Beyond this, something is genuinely wrong.
BOUND_REPAIR_TOLERANCE = 1e-6

# Derived values are rounded a few places finer than the independent ones: enough to clear
# floating-point noise (0.1 + 0.2 artifacts), far too little to disturb any constraint.
DERIVED_EXTRA_DECIMALS = 3


def build_hourly_plan(
    request: OptimizeRequest,
    compiled: CompiledConstraints,
    solution: np.ndarray,
    *,
    decimals: int | None,
    settings: Settings | None = None,
) -> list[HourPlan]:
    """Build the 24 response entries from a solution vector.

    ``decimals`` rounds the independent decisions to that many places; ``None`` keeps full
    precision. The caller uses the second form as a fallback when rounding would cost more
    accuracy than the plan can spare.
    """
    settings = settings or get_settings()
    epsilon = settings.solver_epsilon
    hours = request.canonical_hours()
    battery = request.battery

    charge = _canonicalize(solution[CHARGE], epsilon)
    discharge = _canonicalize(solution[DISCHARGE], epsilon)
    solar_used = _canonicalize(solution[SOLAR], epsilon)

    if decimals is not None:
        charge = np.round(charge, decimals)
        discharge = np.round(discharge, decimals)
        solar_used = np.round(solar_used, decimals)

    charge = _fit_to_bound(charge, battery.max_charge_kwh_per_hour, "charge")
    discharge = _fit_to_bound(discharge, battery.max_discharge_kwh_per_hour, "discharge")
    solar_used = _fit_to_bound(solar_used, compiled.effective_solar, "solar_used")

    _reject_banned_activity(charge, compiled.charge_allowed, "charge", epsilon)
    _reject_banned_activity(discharge, compiled.discharge_allowed, "discharge", epsilon)

    both_active = np.flatnonzero((charge > epsilon) & (discharge > epsilon))
    if both_active.size:
        listed = ", ".join(str(int(hour)) for hour in both_active)
        raise SolverFailure(f"solution charges and discharges in the same hour(s): {listed}")

    derived_decimals = None if decimals is None else decimals + DERIVED_EXTRA_DECIMALS
    plan: list[HourPlan] = []
    energy_before = float(battery.initial_energy_kwh)

    for index in range(HOURS_IN_DAY):
        hour_input = hours[index]
        charged = float(charge[index])
        discharged = float(discharge[index])
        solar = float(solar_used[index])

        if charged > epsilon:
            action, magnitude = "charge", charged
        elif discharged > epsilon:
            action, magnitude = "discharge", discharged
        else:
            # Derived from the magnitudes, not from the binary mode variables: a mode flag set
            # with a zero amount is still an idle hour.
            action, magnitude = "idle", 0.0
            charged = discharged = 0.0

        energy_after = _round(energy_before + charged - discharged, derived_decimals)
        grid = _round(hour_input.demand_kwh + charged - solar - discharged, derived_decimals)
        if -BOUND_REPAIR_TOLERANCE < grid < 0.0:
            grid = 0.0

        try:
            plan.append(
                HourPlan(
                    hour=hour_input.hour,
                    grid_kwh=grid,
                    solar_used_kwh=solar,
                    battery_action=action,
                    battery_kwh=magnitude,
                    battery_energy_after_kwh=energy_after,
                )
            )
        except ValidationError as exc:
            # The response model's own guards (non-negative values, zero magnitude when idle)
            # reject the entry. Surface it as a classified solver failure rather than letting a
            # raw validation error escape into the generic 500 handler.
            raise SolverFailure(
                f"the schedule is not representable at hour {hour_input.hour}",
                details=[error["msg"] for error in exc.errors()[:3]],
            ) from exc

        energy_before = energy_after

    return plan


def _canonicalize(values: np.ndarray, epsilon: float) -> np.ndarray:
    """Zero out floating-point dust without touching a materially negative value."""
    cleaned = np.array(values, dtype=float, copy=True)
    cleaned[np.abs(cleaned) < epsilon] = 0.0
    return cleaned


def _fit_to_bound(values: np.ndarray, upper: float | np.ndarray, label: str) -> np.ndarray:
    """Clip rounding overshoot back inside a bound; reject anything bigger."""
    if np.isscalar(upper):
        upper_array = np.full(HOURS_IN_DAY, float(upper))
    else:
        upper_array = np.asarray(upper, dtype=float)

    overshoot = values - upper_array
    material = np.flatnonzero(overshoot > BOUND_REPAIR_TOLERANCE)
    if material.size:
        listed = ", ".join(str(int(hour)) for hour in material)
        raise SolverFailure(f"{label} exceeds its limit at hour(s) {listed}")

    undershoot = np.flatnonzero(values < -BOUND_REPAIR_TOLERANCE)
    if undershoot.size:
        listed = ", ".join(str(int(hour)) for hour in undershoot)
        raise SolverFailure(f"{label} is negative at hour(s) {listed}")

    return np.clip(values, 0.0, upper_array)


def _reject_banned_activity(
    values: np.ndarray, allowed: np.ndarray, label: str, epsilon: float
) -> None:
    """A banned hour showing real activity is a solver fault, not something to silently zero."""
    offenders = np.flatnonzero((~allowed) & (values > epsilon))
    if offenders.size:
        listed = ", ".join(str(int(hour)) for hour in offenders)
        raise SolverFailure(f"{label} occurs during a prohibited hour(s) {listed}")


def _round(value: float, decimals: int | None) -> float:
    return value if decimals is None else float(round(value, decimals))


__all__ = ["BOUND_REPAIR_TOLERANCE", "build_hourly_plan"]
