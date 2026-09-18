"""Response totals, recalculated from the plan that is actually being returned.

The judge recomputes ``total_grid_kwh``, ``total_cost_bdt``, and ``peak_grid_kwh`` from
``hourly_plan`` and compares them with the reported values, so the plan is the single source
of truth. A total is never taken from the LLM or carried over from a solver objective.

``math.fsum`` is used rather than ``sum`` because the cost is a sum of 24 products that may
differ in magnitude; exact summation keeps the recalculated total from drifting away from the
reported one for reasons that have nothing to do with the schedule.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.schemas.response import HourPlan


@dataclass(frozen=True)
class PlanTotals:
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float


def recalculate_totals(plan: Sequence[HourPlan], tariff_by_hour: Mapping[int, float]) -> PlanTotals:
    """Recompute the three reported totals from the plan entries.

    ``tariff_by_hour`` is keyed by the hour number, never by array position, so a plan listed
    in an unexpected order still costs each hour at its own tariff.
    """
    if not plan:
        return PlanTotals(total_grid_kwh=0.0, total_cost_bdt=0.0, peak_grid_kwh=0.0)

    grid_values = [entry.grid_kwh for entry in plan]
    return PlanTotals(
        total_grid_kwh=math.fsum(grid_values),
        total_cost_bdt=math.fsum(entry.grid_kwh * tariff_by_hour[entry.hour] for entry in plan),
        peak_grid_kwh=max(grid_values),
    )


__all__ = ["PlanTotals", "recalculate_totals"]
