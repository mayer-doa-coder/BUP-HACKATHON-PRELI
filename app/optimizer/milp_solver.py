"""Stage B — the authoritative MILP.

The same model again, now with the charge/discharge mode variables restricted to ``{0, 1}``.
This is the only solver output the response is ever built from (D-02).

Why the integrality matters even though it does not change the optimal *cost*: any relaxed
solution that charges and discharges in the same hour can be rewritten as the net movement
without changing the objective, so the LP bound and the MILP optimum coincide here. What the
binaries buy is a schedule that is *expressible* in the response contract, where each hour has
exactly one ``battery_action``. Cost parity is a property of this particular problem, not
something to rely on: the MILP is still solved and its solution is still what gets returned.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from app.config import Settings, get_settings
from app.optimizer.model import OptimizationModel

# scipy.optimize.milp status codes.
_SCIPY_OPTIMAL = 0
_SCIPY_LIMIT_REACHED = 1
_SCIPY_INFEASIBLE = 2
_SCIPY_UNBOUNDED = 3


class MilpStatus(StrEnum):
    OPTIMAL = "optimal"
    # A feasible incumbent found before a time/iteration limit stopped the proof of optimality.
    FEASIBLE_NOT_PROVEN = "feasible_not_proven"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    ERROR = "error"


@dataclass(frozen=True)
class MilpResult:
    status: MilpStatus
    cost: float | None
    solution: np.ndarray | None
    duration_ms: float
    mip_gap: float | None = None
    dual_bound: float | None = None
    solver_message: str = ""

    @property
    def is_usable(self) -> bool:
        """Whether a schedule can be built from this result.

        A time-limited but feasible incumbent counts: a valid, slightly suboptimal plan still
        earns directive-application credit and partial optimization credit, whereas failing the
        request earns nothing. Validity is never traded away — the independent replay still has
        the final say.
        """
        usable_statuses = (MilpStatus.OPTIMAL, MilpStatus.FEASIBLE_NOT_PROVEN)
        return self.status in usable_statuses and self.solution is not None

    @property
    def proven_optimal(self) -> bool:
        return self.status is MilpStatus.OPTIMAL


def solve_milp(model: OptimizationModel, settings: Settings | None = None) -> MilpResult:
    """Solve the mixed-integer model. Solver problems become statuses, never exceptions."""
    settings = settings or get_settings()
    started = time.perf_counter()

    constraints = [
        LinearConstraint(model.a_eq, model.b_eq, model.b_eq),
        LinearConstraint(model.a_ub, -np.inf, model.b_ub),
    ]

    try:
        result = milp(
            model.objective,
            integrality=model.integrality,
            bounds=Bounds(model.lower_bounds, model.upper_bounds),
            constraints=constraints,
            options={
                "time_limit": settings.milp_time_limit_seconds,
                # Explicit: without this HiGHS stops at its default 1e-4 relative gap and still
                # reports success, so a slightly suboptimal plan would be labelled optimal.
                "mip_rel_gap": settings.milp_relative_gap,
            },
        )
    except Exception as exc:  # noqa: BLE001 - any solver failure becomes a controlled status
        return MilpResult(
            status=MilpStatus.ERROR,
            cost=None,
            solution=None,
            duration_ms=(time.perf_counter() - started) * 1000.0,
            solver_message=type(exc).__name__,
        )

    duration_ms = (time.perf_counter() - started) * 1000.0
    message = str(getattr(result, "message", ""))
    mip_gap = _optional_float(getattr(result, "mip_gap", None))
    dual_bound = _optional_float(getattr(result, "mip_dual_bound", None))
    solution = None if result.x is None else np.asarray(result.x, dtype=float)

    if result.status == _SCIPY_INFEASIBLE:
        status = MilpStatus.INFEASIBLE
    elif result.status == _SCIPY_UNBOUNDED:
        status = MilpStatus.UNBOUNDED
    elif result.status == _SCIPY_OPTIMAL:
        status = MilpStatus.OPTIMAL
    elif result.status == _SCIPY_LIMIT_REACHED and solution is not None:
        status = MilpStatus.FEASIBLE_NOT_PROVEN
    else:
        status = MilpStatus.ERROR

    if status in (MilpStatus.OPTIMAL, MilpStatus.FEASIBLE_NOT_PROVEN):
        if solution is None or not np.isfinite(solution).all() or not np.isfinite(result.fun):
            return MilpResult(
                status=MilpStatus.ERROR,
                cost=None,
                solution=None,
                duration_ms=duration_ms,
                solver_message="non-finite MILP solution",
            )
        return MilpResult(
            status=status,
            cost=float(result.fun),
            solution=solution,
            duration_ms=duration_ms,
            mip_gap=mip_gap,
            dual_bound=dual_bound,
            solver_message=message,
        )

    return MilpResult(
        status=status,
        cost=None,
        solution=None,
        duration_ms=duration_ms,
        mip_gap=mip_gap,
        dual_bound=dual_bound,
        solver_message=message,
    )


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        converted = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return converted if np.isfinite(converted) else None


__all__ = ["MilpResult", "MilpStatus", "solve_milp"]
