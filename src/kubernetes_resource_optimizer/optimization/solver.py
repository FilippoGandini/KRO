"""Small solver boundary around PuLP's bundled CBC backend."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter

import pulp


class SolverStatus(StrEnum):
    """Solver states exposed independently of PuLP status constants."""

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    NOT_SOLVED = "not_solved"
    UNDEFINED = "undefined"


@dataclass(frozen=True, slots=True)
class SolverResult:
    """Summary returned after solving a model."""

    status: SolverStatus
    objective_value: float | None
    solve_time_seconds: float


@dataclass(frozen=True, slots=True)
class CbcSolver:
    """Solve PuLP MILP models with the bundled open-source CBC executable."""

    time_limit_seconds: float | None = None
    mip_gap: float | None = None
    log_output: bool = False

    def __post_init__(self) -> None:
        if self.time_limit_seconds is not None and (
            not math.isfinite(self.time_limit_seconds)
            or self.time_limit_seconds <= 0
        ):
            raise ValueError("time_limit_seconds must be finite and positive")
        if self.mip_gap is not None and (
            not math.isfinite(self.mip_gap) or not 0 <= self.mip_gap <= 1
        ):
            raise ValueError("mip_gap must be finite and between 0 and 1")

    def solve(self, model: pulp.LpProblem) -> SolverResult:
        """Solve ``model`` and return a solver-independent result summary.

        PuLP updates the model's variables in place, so callers can inspect
        variable values, named constraints, or export the model after solving.
        """

        solver = pulp.COIN_CMD(
            msg=self.log_output,
            timeLimit=self.time_limit_seconds,
            gapRel=self.mip_gap,
            path=pulp.PULP_CBC_CMD.pulp_cbc_path,
        )
        started_at = perf_counter()
        raw_status = model.solve(solver)
        solve_time_seconds = perf_counter() - started_at

        status = _normalize_status(raw_status, model.sol_status)
        objective_value = (
            float(pulp.value(model.objective))
            if status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
            else None
        )
        return SolverResult(
            status=status,
            objective_value=objective_value,
            solve_time_seconds=solve_time_seconds,
        )


def _normalize_status(raw_status: int, solution_status: int) -> SolverStatus:
    if solution_status == pulp.LpSolutionIntegerFeasible:
        return SolverStatus.FEASIBLE

    statuses = {
        pulp.LpStatusOptimal: SolverStatus.OPTIMAL,
        pulp.LpStatusInfeasible: SolverStatus.INFEASIBLE,
        pulp.LpStatusUnbounded: SolverStatus.UNBOUNDED,
        pulp.LpStatusNotSolved: SolverStatus.NOT_SOLVED,
        pulp.LpStatusUndefined: SolverStatus.UNDEFINED,
    }
    return statuses.get(raw_status, SolverStatus.UNDEFINED)
