"""Local solver boundary for PuLP MILP models."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Protocol

import pulp


class SolverName(StrEnum):
    """Supported local MILP solvers."""

    HIGHS = "highs"
    CBC = "cbc"

    @property
    def display_name(self) -> str:
        return {
            SolverName.HIGHS: "HiGHS",
            SolverName.CBC: "CBC",
        }[self]


class SolverStatus(StrEnum):
    """Solver states exposed independently of PuLP status constants."""

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    NOT_SOLVED = "not_solved"
    UNDEFINED = "undefined"


@dataclass(frozen=True, slots=True)
class StageResult:
    """Objective optimum/incumbent and termination state of one phase."""

    name: str
    status: SolverStatus
    objective_value: float | None
    solve_time_seconds: float


@dataclass(frozen=True, slots=True)
class SolverResult:
    """Summary returned after solving a model."""

    status: SolverStatus
    objective_value: float | None
    solve_time_seconds: float
    solver: SolverName = SolverName.CBC
    stages: tuple[StageResult, ...] = ()
    lexicographic_complete: bool = False
    message: str = ""


class MilpSolver(Protocol):
    """Minimal interface implemented by all local solver adapters."""

    def solve(self, model: pulp.LpProblem) -> SolverResult: ...


def _validate_options(time_limit_seconds: float | None, mip_gap: float | None) -> None:
    if time_limit_seconds is not None and (
        not math.isfinite(time_limit_seconds) or time_limit_seconds <= 0
    ):
        raise ValueError("time_limit_seconds must be finite and positive")
    if mip_gap is not None and (not math.isfinite(mip_gap) or not 0 <= mip_gap <= 1):
        raise ValueError("mip_gap must be finite and between 0 and 1")


def _solve(
    model: pulp.LpProblem, command: pulp.LpSolver, solver: SolverName
) -> SolverResult:
    if not command.available():
        raise RuntimeError(
            f"{solver.display_name} is not available; install its local dependency"
        )

    started_at = perf_counter()
    raw_status = model.solve(command)
    solve_time_seconds = perf_counter() - started_at
    status = _normalize_status(raw_status, model.sol_status)
    objective_value = (
        float(pulp.value(model.objective) or 0.0)
        if status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
        else None
    )
    return SolverResult(status, objective_value, solve_time_seconds, solver)


@dataclass(frozen=True, slots=True)
class HighsSolver:
    """Solve in-process through the local ``highspy`` Python package."""

    time_limit_seconds: float | None = None
    mip_gap: float | None = None
    log_output: bool = False

    def __post_init__(self) -> None:
        _validate_options(self.time_limit_seconds, self.mip_gap)

    def solve(self, model: pulp.LpProblem) -> SolverResult:
        command = pulp.HiGHS(
            msg=self.log_output,
            timeLimit=self.time_limit_seconds,
            gapRel=self.mip_gap,
            gapAbs=0.0,
        )
        return _solve(model, command, SolverName.HIGHS)


@dataclass(frozen=True, slots=True)
class CbcSolver:
    """Solve through PuLP's bundled local CBC command-line executable."""

    time_limit_seconds: float | None = None
    mip_gap: float | None = None
    log_output: bool = False

    def __post_init__(self) -> None:
        _validate_options(self.time_limit_seconds, self.mip_gap)

    def solve(self, model: pulp.LpProblem) -> SolverResult:
        """Solve ``model`` and return a solver-independent result summary.

        PuLP updates the model's variables in place, so callers can inspect
        variable values, named constraints, or export the model after solving.
        """

        solver = pulp.COIN_CMD(
            msg=self.log_output,
            timeLimit=self.time_limit_seconds,
            gapRel=self.mip_gap,
            gapAbs=0.0,
            path=pulp.PULP_CBC_CMD.pulp_cbc_path,
        )
        return _solve(model, solver, SolverName.CBC)


def create_solver(
    solver: SolverName = SolverName.HIGHS,
    *,
    time_limit_seconds: float | None = None,
    mip_gap: float | None = None,
    log_output: bool = False,
) -> HighsSolver | CbcSolver:
    """Create the selected local solver; HiGHS is the application default."""

    if solver is SolverName.HIGHS:
        return HighsSolver(time_limit_seconds, mip_gap, log_output)
    return CbcSolver(time_limit_seconds, mip_gap, log_output)


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
