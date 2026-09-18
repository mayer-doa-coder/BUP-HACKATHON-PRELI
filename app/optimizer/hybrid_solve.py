"""LP-assisted MILP orchestration.

Two coordinated stages over one model (D-02):

1. the LP relaxation screens feasibility and produces a lower bound;
2. the MILP produces the authoritative schedule;
3. the two are cross-checked, and the MILP solution is sanity-gated before anyone builds a
   response from it.

**Failures are returned as statuses, not raised.** The distinction between "this scenario is
impossible", "this *interpretation* is impossible", and "the solver broke" drives three
different outcomes — a 422, a bounded semantic reparse, and a 500 respectively — and that
mapping belongs to the service layer, not here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from app.config import Settings, get_settings
from app.optimizer.compile_directives import CompiledConstraints, compile_directives
from app.optimizer.lp_relaxation import LpResult, solve_lp_relaxation
from app.optimizer.milp_solver import MilpResult, MilpStatus, solve_milp
from app.optimizer.model import CHARGE, DISCHARGE, OptimizationModel, build_model
from app.schemas.directive import DirectiveInterpretation
from app.schemas.request import OptimizeRequest

# Loose enough to accept ordinary HiGHS feasibility slack. The response builder reconstructs
# dependent values afterwards, and the independent replay then checks at internal tolerance.
SOLUTION_RESIDUAL_TOLERANCE = 1e-6


class SolveStatus(StrEnum):
    OK = "ok"
    # The scenario cannot be scheduled even with no directives applied -> semantically invalid.
    BASELINE_INFEASIBLE = "baseline_infeasible"
    # The scenario is fine but this interpretation of the notes cannot be scheduled.
    DIRECTIVE_INFEASIBLE = "directive_infeasible"
    # The solver misbehaved, or an internal invariant broke.
    SOLVER_FAILURE = "solver_failure"


@dataclass(frozen=True)
class BaselineScreen:
    """Result of the pre-LLM feasibility screen (no directives applied)."""

    feasible: bool
    lp: LpResult

    @property
    def lower_bound_cost(self) -> float | None:
        """Cheapest possible cost before any directive tightens the problem."""
        return self.lp.cost


@dataclass(frozen=True)
class SolveOutcome:
    status: SolveStatus
    compiled: CompiledConstraints | None = None
    model: OptimizationModel | None = None
    lp: LpResult | None = None
    milp: MilpResult | None = None
    solution: np.ndarray | None = None
    cost: float | None = None
    proven_optimal: bool = False
    detail: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status is SolveStatus.OK

    @property
    def lp_lower_bound(self) -> float | None:
        return self.lp.cost if self.lp is not None else None


def screen_baseline_feasibility(
    request: OptimizeRequest, settings: Settings | None = None
) -> BaselineScreen:
    """Solve the scenario with **no** operator directives.

    Run before the LLM for two reasons: a structurally valid but impossible scenario should not
    spend a paid call, and — more importantly — it separates "the scenario is broken" from "the
    interpretation is wrong". Without this screen, a later infeasibility would be ambiguous.
    """
    settings = settings or get_settings()
    compiled = compile_directives(request, [], settings)
    model = build_model(request, compiled)
    lp = solve_lp_relaxation(model, settings)
    return BaselineScreen(feasible=lp.is_optimal, lp=lp)


def hybrid_solve(
    request: OptimizeRequest,
    directives: Sequence[DirectiveInterpretation],
    settings: Settings | None = None,
) -> SolveOutcome:
    """Compile, relax, solve, and cross-check. The returned solution is the MILP's."""
    settings = settings or get_settings()

    compiled = compile_directives(request, directives, settings)
    model = build_model(request, compiled)

    lp = solve_lp_relaxation(model, settings)
    if lp.is_infeasible:
        return SolveOutcome(
            status=SolveStatus.DIRECTIVE_INFEASIBLE,
            compiled=compiled,
            model=model,
            lp=lp,
            detail=("the directive-constrained LP relaxation is infeasible",),
        )
    if not lp.is_optimal:
        return SolveOutcome(
            status=SolveStatus.SOLVER_FAILURE,
            compiled=compiled,
            model=model,
            lp=lp,
            detail=(f"LP relaxation returned status {lp.status}",),
        )

    milp = solve_milp(model, settings)
    if milp.status is MilpStatus.INFEASIBLE:
        # Every relaxed solution that charges and discharges in one hour can be rewritten as the
        # net movement, so a feasible relaxation implies a feasible integral solution. Reaching
        # here means the model or the solver is wrong, not that the directives are impossible.
        return SolveOutcome(
            status=SolveStatus.SOLVER_FAILURE,
            compiled=compiled,
            model=model,
            lp=lp,
            milp=milp,
            detail=("MILP infeasible although the LP relaxation was feasible",),
        )
    if not milp.is_usable:
        return SolveOutcome(
            status=SolveStatus.SOLVER_FAILURE,
            compiled=compiled,
            model=model,
            lp=lp,
            milp=milp,
            detail=(f"MILP returned status {milp.status}",),
        )

    solution = milp.solution
    if solution is None or milp.cost is None:  # unreachable via is_usable, kept as a hard guard
        return SolveOutcome(
            status=SolveStatus.SOLVER_FAILURE,
            compiled=compiled,
            model=model,
            lp=lp,
            milp=milp,
            detail=("MILP reported success without a solution",),
        )

    problems = _invariant_problems(model, lp, milp, solution, settings)
    if problems:
        return SolveOutcome(
            status=SolveStatus.SOLVER_FAILURE,
            compiled=compiled,
            model=model,
            lp=lp,
            milp=milp,
            detail=tuple(problems),
        )

    return SolveOutcome(
        status=SolveStatus.OK,
        compiled=compiled,
        model=model,
        lp=lp,
        milp=milp,
        solution=solution,
        cost=milp.cost,
        proven_optimal=milp.proven_optimal,
    )


def _invariant_problems(
    model: OptimizationModel,
    lp: LpResult,
    milp: MilpResult,
    solution: np.ndarray,
    settings: Settings,
) -> list[str]:
    """Checks that must hold before a response is built from this solution."""
    problems: list[str] = []

    # 1. The relaxation is a lower bound. A MILP objective below it means the two stages did not
    #    solve the same problem, which would invalidate every other comparison.
    if lp.cost is not None and milp.cost is not None:
        tolerance = max(settings.internal_tolerance, abs(lp.cost) * 1e-9)
        if milp.cost + tolerance < lp.cost:
            problems.append(
                f"MILP objective {milp.cost} is below the LP lower bound {lp.cost} beyond tolerance"
            )

    # 2. The solution really satisfies the system it was solved against.
    equality_error, inequality_error, bound_error = model.residuals(solution)
    if max(equality_error, inequality_error, bound_error) > SOLUTION_RESIDUAL_TOLERANCE:
        problems.append(
            f"MILP solution residuals out of tolerance "
            f"(eq={equality_error:.3g}, ub={inequality_error:.3g}, bound={bound_error:.3g})"
        )

    # 3. Charge and discharge are mutually exclusive. The binaries should guarantee this; an
    #    hour doing both cannot be expressed as a single battery_action, so it fails closed.
    charge = solution[CHARGE]
    discharge = solution[DISCHARGE]
    both_active = np.flatnonzero(
        (charge > SOLUTION_RESIDUAL_TOLERANCE) & (discharge > SOLUTION_RESIDUAL_TOLERANCE)
    )
    if both_active.size:
        hours = ", ".join(str(int(hour)) for hour in both_active)
        problems.append(f"MILP charges and discharges in the same hour(s): {hours}")

    return problems


__all__ = [
    "SOLUTION_RESIDUAL_TOLERANCE",
    "BaselineScreen",
    "SolveOutcome",
    "SolveStatus",
    "hybrid_solve",
    "screen_baseline_feasibility",
]
