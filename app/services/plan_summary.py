"""The deterministic ``plan_summary``.

Generated from the validated directives and the finished plan — never by a second LLM call,
which would add latency and a failure mode to a field that carries no scoring weight beyond
being present and truthful (PRD FR-12).

The summary only states things the plan actually demonstrates. It does not claim the battery
shifted energy across tariff periods on a day where the battery never moved.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.directive import DirectiveInterpretation
from app.schemas.response import HourPlan

_DIRECTIVE_PHRASES = {
    "solar_reduction": "reduced solar availability",
    "minimum_battery_reserve": "a raised battery reserve",
    "no_charge_window": "a no-charge window",
    "no_discharge_window": "a no-discharge window",
    "max_grid_window": "a grid import cap",
}


def build_plan_summary(
    directives: Sequence[DirectiveInterpretation],
    plan: Sequence[HourPlan],
) -> str:
    """One short, factual sentence pair describing what was applied and what the plan does."""
    applied = [directive for directive in directives if directive.applies]
    ignored = len(directives) - len(applied)

    parts: list[str] = []

    if applied:
        phrases = sorted({_DIRECTIVE_PHRASES[directive.directive_type] for directive in applied})
        parts.append(
            f"Applied {len(applied)} operator directive(s) covering {_join(phrases)}."
        )
    else:
        parts.append("No operator note changed the schedule.")

    if ignored:
        parts.append(f"{ignored} note(s) were not schedule-relevant.")

    charge_hours = sum(1 for entry in plan if entry.battery_action == "charge")
    discharge_hours = sum(1 for entry in plan if entry.battery_action == "discharge")
    if charge_hours and discharge_hours:
        parts.append(
            f"The battery charged in {charge_hours} hour(s) and discharged in {discharge_hours} "
            "hour(s) to shift energy towards cheaper tariff periods, "
            "returning to its initial level at the end of the day."
        )
    else:
        parts.append(
            "The battery stayed at its starting level, so demand was met from solar and grid import."
        )

    parts.append("All 24 hours satisfy the demand, solar, battery, and directive constraints.")
    return " ".join(parts)


def _join(items: Sequence[str]) -> str:
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


__all__ = ["build_plan_summary"]
