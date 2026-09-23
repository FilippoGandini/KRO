"""Local solver boundary for PuLP MILP models."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Protocol

import pulp

# Classification only: do not change solver targets or objective lock tolerances.
_HIGHS_NUMERICAL_GAP_TOLERANCE = 1e-12


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
    GAP_SATISFIED = "gap_satisfied"
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
    mip_gap: float | None = None
    best_bound: float | None = None


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
    mip_gap: float | None = None
    best_bound: float | None = None


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
        result = _solve(model, command, SolverName.HIGHS)
        info = model.solverModel.getInfo()
        gap: float | None = float(info.mip_gap)
        bound: float | None = float(info.mip_dual_bound)
        gap = gap if gap is not None and math.isfinite(gap) else None
        bound = bound if bound is not None and math.isfinite(bound) else None
        status = result.status
        # HiGHS reports kOptimal also when its relative gap target is reached.
        # Preserve optimality for floating-point residuals, keeping the raw gap
        # for diagnostics. A time stop must never be promoted by this tolerance.
        if (
            status is SolverStatus.OPTIMAL
            and gap is not None
            and gap > _HIGHS_NUMERICAL_GAP_TOLERANCE
        ):
            status = (
                SolverStatus.GAP_SATISFIED
                if self.mip_gap is not None and gap <= self.mip_gap
                else SolverStatus.FEASIBLE
            )
        return replace(result, status=status, mip_gap=gap, best_bound=bound)


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

        # CBC's PuLP status loses the distinction between exact and gap termination.
        # Read the explicit termination reason from its local log instead.
        with TemporaryDirectory(prefix=".cbc-log-", dir=".") as directory:
            log = Path(directory) / "solve.log"
            solver = pulp.COIN_CMD(
                msg=False,
                timeLimit=self.time_limit_seconds,
                gapRel=self.mip_gap,
                gapAbs=0.0,
                path=pulp.PULP_CBC_CMD.pulp_cbc_path,
                logPath=str(log),
            )
            result = _solve(model, solver, SolverName.CBC)
            output = log.read_text()
            if self.log_output:
                print(output, end="")
            return _cbc_termination(result, output)


def _cbc_termination(result: SolverResult, output: str) -> SolverResult:
    """Use CBC's certified stop reason; printed gap/bound are rounded diagnostics."""
    gap_match = re.search(r"^Gap:\s+([-+0-9.eE]+)", output, re.MULTILINE)
    bound_match = re.search(
        r"^(?:Upper|Lower) bound:\s+([-+0-9.eE]+)", output, re.MULTILINE
    )
    status = result.status
    if (
        "Optimal solution found (within gap tolerance)" in output
        and result.objective_value is not None
    ):
        status = SolverStatus.GAP_SATISFIED
    elif "Stopped on time limit" in output and result.objective_value is not None:
        status = SolverStatus.FEASIBLE
    return replace(
        result,
        status=status,
        mip_gap=abs(float(gap_match[1]))
        if gap_match
        else (0.0 if status is SolverStatus.OPTIMAL else None),
        best_bound=float(bound_match[1]) if bound_match else None,
    )


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
