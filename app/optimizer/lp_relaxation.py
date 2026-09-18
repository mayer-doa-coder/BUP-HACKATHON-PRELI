"""Stage A — the LP relaxation.

The same model as the MILP, with the charge/discharge mode variables left continuous in
``[0, 1]``. It serves three purposes and is never returned to the judge as a schedule:

* **feasibility screening** — cheap enough to run before any paid LLM call;
* **a lower bound** on the minimum achievable grid cost, used to cross-check the MILP;
* **diagnostics** — solver status and timing for the observability layer.

``linprog`` is handed the model exactly as ``build_model`` produced it. Nothing is relaxed by
editing the matrices: the relaxation *is* the model without the integrality vector applied.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from scipy.optimize import linprog

from app.config import Settings, get_settings
from app.optimizer.model import OptimizationModel

# scipy.optimize.linprog status codes.
_SCIPY_OPTIMAL = 0
_SCIPY_ITERATION_LIMIT = 1
_SCIPY_INFEASIBLE = 2
_SCIPY_UNBOUNDED = 3


class LpStatus(StrEnum):
    OPTIMAL = "optimal"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    LIMIT = "limit"
    ERROR = "error"


@dataclass(frozen=True)
class LpResult:
    status: LpStatus
    cost: float | None
    solution: np.ndarray | None
    duration_ms: float
    solver_message: str = ""

    @property
    def is_optimal(self) -> bool:
        return self.status is LpStatus.OPTIMAL

    @property
    def is_infeasible(self) -> bool:
        return self.status is LpStatus.INFEASIBLE


def solve_lp_relaxation(model: OptimizationModel, settings: Settings | None = None) -> LpResult:
    """Solve the continuous relaxation.

    Never raises for a solver-level problem: an infeasible or failed solve is a *status*, so the
    caller can tell "this scenario cannot be scheduled" apart from "the solver broke", which map
    to different HTTP responses.
    """
    settings = settings or get_settings()
    started = time.perf_counter()

    try:
        result = linprog(
            model.objective,
            A_ub=model.a_ub,
            b_ub=model.b_ub,
            A_eq=model.a_eq,
            b_eq=model.b_eq,
            bounds=model.scipy_bounds(),
            method=settings.lp_solver_method,
        )
    except Exception as exc:  # noqa: BLE001 - any solver failure becomes a controlled status
        duration_ms = (time.perf_counter() - started) * 1000.0
        return LpResult(
            status=LpStatus.ERROR,
            cost=None,
            solution=None,
            duration_ms=duration_ms,
            solver_message=type(exc).__name__,
        )

    duration_ms = (time.perf_counter() - started) * 1000.0
    status = _map_status(result.status)
    if status is not LpStatus.OPTIMAL:
        return LpResult(
            status=status,
            cost=None,
            solution=None,
            duration_ms=duration_ms,
            solver_message=str(getattr(result, "message", "")),
        )

    solution = np.asarray(result.x, dtype=float)
    if not np.isfinite(solution).all() or not np.isfinite(result.fun):
        return LpResult(
            status=LpStatus.ERROR,
            cost=None,
            solution=None,
            duration_ms=duration_ms,
            solver_message="non-finite LP solution",
        )

    return LpResult(
        status=LpStatus.OPTIMAL,
        cost=float(result.fun),
        solution=solution,
        duration_ms=duration_ms,
        solver_message=str(getattr(result, "message", "")),
    )


def _map_status(scipy_status: int) -> LpStatus:
    if scipy_status == _SCIPY_OPTIMAL:
        return LpStatus.OPTIMAL
    if scipy_status == _SCIPY_INFEASIBLE:
        return LpStatus.INFEASIBLE
    if scipy_status == _SCIPY_UNBOUNDED:
        return LpStatus.UNBOUNDED
    if scipy_status == _SCIPY_ITERATION_LIMIT:
        return LpStatus.LIMIT
    return LpStatus.ERROR


__all__ = ["LpResult", "LpStatus", "solve_lp_relaxation"]
