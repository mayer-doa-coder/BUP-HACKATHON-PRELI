"""The shared LP/MILP optimization model.

One variable layout and one constraint system feed **both** solver stages. The LP relaxation
and the authoritative MILP differ in exactly one respect — whether ``yc``/``yd`` are forced to
be integral — and that difference lives in the ``integrality`` vector, not in a second model
builder. There is deliberately no ``stage`` parameter here: if the two stages could be built
differently, the invariant ``LP_cost <= MILP_cost`` would stop meaning anything, because the
two numbers could come from different problems.

Variable layout (Guide §12), 168 variables in total::

    0..23      g   grid import
    24..47     s   solar used
    48..71     c   battery charge amount
    72..95     d   battery discharge amount
    96..119    E   battery energy after the hour
    120..143   yc  charge-mode indicator
    144..167   yd  discharge-mode indicator

Constraints (Problem Statement §09)::

    g[h] + s[h] + d[h] - c[h] = demand[h]              24 equalities
    E[0] - c[0] + d[0] = initial_energy                 1 equality
    E[h] - E[h-1] - c[h] + d[h] = 0     for h > 0      23 equalities
    E[23] = initial_energy                              1 equality  (end-of-day neutrality)
    c[h] - max_charge * yc[h] <= 0                     24 inequalities
    d[h] - max_discharge * yd[h] <= 0                  24 inequalities
    yc[h] + yd[h] <= 1                                 24 inequalities

Everything a directive changes — reduced solar, a raised reserve floor, a grid cap, a charge or
discharge ban — arrives as a **bound**, already resolved by the directive compiler. This module
never inspects a directive.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.optimizer.compile_directives import CompiledConstraints
from app.schemas.request import HOURS_IN_DAY, OptimizeRequest

# Offsets of each variable block within the solution vector.
GRID_OFFSET = 0
SOLAR_OFFSET = HOURS_IN_DAY
CHARGE_OFFSET = 2 * HOURS_IN_DAY
DISCHARGE_OFFSET = 3 * HOURS_IN_DAY
ENERGY_OFFSET = 4 * HOURS_IN_DAY
CHARGE_MODE_OFFSET = 5 * HOURS_IN_DAY
DISCHARGE_MODE_OFFSET = 6 * HOURS_IN_DAY

VARIABLE_COUNT = 7 * HOURS_IN_DAY  # 168
EQUALITY_ROWS = 2 * HOURS_IN_DAY + 1  # balance + transition + neutrality
INEQUALITY_ROWS = 3 * HOURS_IN_DAY  # charge link + discharge link + mode exclusivity

GRID = slice(GRID_OFFSET, GRID_OFFSET + HOURS_IN_DAY)
SOLAR = slice(SOLAR_OFFSET, SOLAR_OFFSET + HOURS_IN_DAY)
CHARGE = slice(CHARGE_OFFSET, CHARGE_OFFSET + HOURS_IN_DAY)
DISCHARGE = slice(DISCHARGE_OFFSET, DISCHARGE_OFFSET + HOURS_IN_DAY)
ENERGY = slice(ENERGY_OFFSET, ENERGY_OFFSET + HOURS_IN_DAY)
CHARGE_MODE = slice(CHARGE_MODE_OFFSET, CHARGE_MODE_OFFSET + HOURS_IN_DAY)
DISCHARGE_MODE = slice(DISCHARGE_MODE_OFFSET, DISCHARGE_MODE_OFFSET + HOURS_IN_DAY)


def grid_index(hour: int) -> int:
    return GRID_OFFSET + hour


def solar_index(hour: int) -> int:
    return SOLAR_OFFSET + hour


def charge_index(hour: int) -> int:
    return CHARGE_OFFSET + hour


def discharge_index(hour: int) -> int:
    return DISCHARGE_OFFSET + hour


def energy_index(hour: int) -> int:
    return ENERGY_OFFSET + hour


def charge_mode_index(hour: int) -> int:
    return CHARGE_MODE_OFFSET + hour


def discharge_mode_index(hour: int) -> int:
    return DISCHARGE_MODE_OFFSET + hour


@dataclass(frozen=True)
class SolutionVectors:
    """A solution vector split back into its per-hour series."""

    grid: np.ndarray
    solar_used: np.ndarray
    charge: np.ndarray
    discharge: np.ndarray
    energy: np.ndarray
    charge_mode: np.ndarray
    discharge_mode: np.ndarray


@dataclass(frozen=True)
class OptimizationModel:
    """The complete linear system, plus the integrality vector the MILP stage applies."""

    objective: np.ndarray
    a_eq: np.ndarray
    b_eq: np.ndarray
    a_ub: np.ndarray
    b_ub: np.ndarray
    lower_bounds: np.ndarray
    upper_bounds: np.ndarray
    integrality: np.ndarray

    def scipy_bounds(self) -> list[tuple[float, float]]:
        """Bounds in the ``[(low, high), ...]`` form ``scipy.optimize.linprog`` expects."""
        pairs = zip(self.lower_bounds, self.upper_bounds, strict=True)
        return [(float(low), float(high)) for low, high in pairs]

    def cost_of(self, solution: np.ndarray) -> float:
        """The objective value of a solution vector: the total grid cost."""
        return float(self.objective @ solution)

    def split(self, solution: np.ndarray) -> SolutionVectors:
        return SolutionVectors(
            grid=solution[GRID],
            solar_used=solution[SOLAR],
            charge=solution[CHARGE],
            discharge=solution[DISCHARGE],
            energy=solution[ENERGY],
            charge_mode=solution[CHARGE_MODE],
            discharge_mode=solution[DISCHARGE_MODE],
        )

    def residuals(self, solution: np.ndarray) -> tuple[float, float, float]:
        """``(max equality error, max inequality overshoot, max bound overshoot)``.

        Used as a cheap solver-output sanity check before the far stricter independent replay.
        """
        equality_error = float(np.max(np.abs(self.a_eq @ solution - self.b_eq))) if len(self.b_eq) else 0.0
        overshoot = np.maximum(self.a_ub @ solution - self.b_ub, 0.0)
        inequality_error = float(np.max(overshoot)) if len(self.b_ub) else 0.0
        bound_error = float(
            np.max(
                np.maximum(
                    np.maximum(self.lower_bounds - solution, 0.0),
                    np.maximum(solution - self.upper_bounds, 0.0),
                )
            )
        )
        return equality_error, inequality_error, bound_error


def build_model(request: OptimizeRequest, compiled: CompiledConstraints) -> OptimizationModel:
    """Assemble the model for one scenario under one set of compiled constraints.

    The same call serves the baseline feasibility screen (compile with no directives), the
    directive-constrained relaxation, and the final MILP.
    """
    hours = request.canonical_hours()
    battery = request.battery
    demand = np.array([entry.demand_kwh for entry in hours], dtype=float)
    tariff = np.array([entry.tariff_bdt_per_kwh for entry in hours], dtype=float)

    max_charge = float(battery.max_charge_kwh_per_hour)
    max_discharge = float(battery.max_discharge_kwh_per_hour)
    initial_energy = float(battery.initial_energy_kwh)

    # --- objective: minimise the cost of imported grid energy ----------------------
    objective = np.zeros(VARIABLE_COUNT, dtype=float)
    objective[GRID] = tariff

    # --- equalities ---------------------------------------------------------------
    a_eq = np.zeros((EQUALITY_ROWS, VARIABLE_COUNT), dtype=float)
    b_eq = np.zeros(EQUALITY_ROWS, dtype=float)

    for hour in range(HOURS_IN_DAY):
        row = hour
        a_eq[row, grid_index(hour)] = 1.0
        a_eq[row, solar_index(hour)] = 1.0
        a_eq[row, discharge_index(hour)] = 1.0
        a_eq[row, charge_index(hour)] = -1.0
        b_eq[row] = demand[hour]

    for hour in range(HOURS_IN_DAY):
        row = HOURS_IN_DAY + hour
        a_eq[row, energy_index(hour)] = 1.0
        a_eq[row, charge_index(hour)] = -1.0
        a_eq[row, discharge_index(hour)] = 1.0
        if hour == 0:
            b_eq[row] = initial_energy
        else:
            a_eq[row, energy_index(hour - 1)] = -1.0
            b_eq[row] = 0.0

    neutrality_row = 2 * HOURS_IN_DAY
    a_eq[neutrality_row, energy_index(HOURS_IN_DAY - 1)] = 1.0
    b_eq[neutrality_row] = initial_energy

    # --- inequalities -------------------------------------------------------------
    a_ub = np.zeros((INEQUALITY_ROWS, VARIABLE_COUNT), dtype=float)
    b_ub = np.zeros(INEQUALITY_ROWS, dtype=float)

    for hour in range(HOURS_IN_DAY):
        charge_link = hour
        a_ub[charge_link, charge_index(hour)] = 1.0
        a_ub[charge_link, charge_mode_index(hour)] = -max_charge

        discharge_link = HOURS_IN_DAY + hour
        a_ub[discharge_link, discharge_index(hour)] = 1.0
        a_ub[discharge_link, discharge_mode_index(hour)] = -max_discharge

        exclusivity = 2 * HOURS_IN_DAY + hour
        a_ub[exclusivity, charge_mode_index(hour)] = 1.0
        a_ub[exclusivity, discharge_mode_index(hour)] = 1.0
        b_ub[exclusivity] = 1.0

    # --- bounds -------------------------------------------------------------------
    lower = np.zeros(VARIABLE_COUNT, dtype=float)
    upper = np.zeros(VARIABLE_COUNT, dtype=float)

    upper[GRID] = compiled.grid_upper
    upper[SOLAR] = compiled.effective_solar

    charge_allowed = compiled.charge_allowed.astype(float)
    discharge_allowed = compiled.discharge_allowed.astype(float)
    # A banned hour pins both the amount and its mode variable to zero, which keeps the
    # relaxation from buying fractional permission to charge.
    upper[CHARGE] = max_charge * charge_allowed
    upper[DISCHARGE] = max_discharge * discharge_allowed
    upper[CHARGE_MODE] = charge_allowed
    upper[DISCHARGE_MODE] = discharge_allowed

    lower[ENERGY] = compiled.min_energy
    upper[ENERGY] = float(battery.capacity_kwh)

    # --- integrality: the MILP stage's only addition -------------------------------
    integrality = np.zeros(VARIABLE_COUNT, dtype=int)
    integrality[CHARGE_MODE] = 1
    integrality[DISCHARGE_MODE] = 1

    return OptimizationModel(
        objective=objective,
        a_eq=a_eq,
        b_eq=b_eq,
        a_ub=a_ub,
        b_ub=b_ub,
        lower_bounds=lower,
        upper_bounds=upper,
        integrality=integrality,
    )


__all__ = [
    "CHARGE",
    "CHARGE_MODE",
    "DISCHARGE",
    "DISCHARGE_MODE",
    "ENERGY",
    "EQUALITY_ROWS",
    "GRID",
    "INEQUALITY_ROWS",
    "SOLAR",
    "VARIABLE_COUNT",
    "OptimizationModel",
    "SolutionVectors",
    "build_model",
    "charge_index",
    "charge_mode_index",
    "discharge_index",
    "discharge_mode_index",
    "energy_index",
    "grid_index",
    "solar_index",
]
