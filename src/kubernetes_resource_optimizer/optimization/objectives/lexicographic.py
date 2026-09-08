"""Sequential MILP solves preserving objective values, not individual allocations."""

from collections.abc import Callable
from dataclasses import replace
from time import perf_counter

import pulp

from kubernetes_resource_optimizer.optimization.model import OptimizationModel
from kubernetes_resource_optimizer.optimization.solver import (
    CbcSolver,
    HighsSolver,
    SolverName,
    SolverResult,
    SolverStatus,
    StageResult,
)


def solve_lexicographic(
    model: OptimizationModel,
    solver: CbcSolver | HighsSolver,
    progress: Callable[[str], None] | None = None,
) -> SolverResult:
    """Share a total time budget and accept a configured relative gap only in fairness.

    Cost is locked with no intentional degradation; normalized objectives use
    the configured absolute tolerance. Solver numerical tolerances still apply.
    A later phase with no incumbent restores the last feasible allocation and
    returns FEASIBLE, never a false claim of complete lexicographic optimality.
    Temporary locks are removed on exit so the model can be solved again.
    """

    if solver.mip_gap not in (None, 0):
        raise ValueError("lexicographic optimization requires mip_gap=0")
    started = perf_counter()
    records: list[StageResult] = []
    snapshot: list[tuple[pulp.LpVariable, float | None]] | None = None
    locks: list[str] = []
    problem = model.problem
    name = SolverName.HIGHS if isinstance(solver, HighsSolver) else SolverName.CBC
    status = SolverStatus.NOT_SOLVED
    message = ""
    last_value: float | None = None
    complete = False
    approximate_fairness = False
    try:
        for index, stage in enumerate(model.stages):
            remaining = None
            if solver.time_limit_seconds is not None:
                remaining = solver.time_limit_seconds - (perf_counter() - started)
                if remaining <= 0:
                    status = (
                        SolverStatus.FEASIBLE
                        if snapshot is not None
                        else SolverStatus.NOT_SOLVED
                    )
                    message = f"Total time budget exhausted before {stage.name}; hierarchy incomplete."
                    break
            if progress:
                progress(
                    f"Optimization phase {index + 1}/{len(model.stages)}: {stage.name}..."
                )
            problem.sense = stage.sense
            problem.setObjective(stage.expression)
            gap = model.config.fairness_mip_gap if stage.name == "fairness" else 0.0
            result = replace(solver, time_limit_seconds=remaining, mip_gap=gap).solve(
                problem
            )
            records.append(
                StageResult(
                    stage.name,
                    result.status,
                    result.objective_value,
                    result.solve_time_seconds,
                    result.mip_gap,
                    result.best_bound,
                )
            )
            status = result.status
            if status in {
                SolverStatus.OPTIMAL,
                SolverStatus.FEASIBLE,
                SolverStatus.GAP_SATISFIED,
            }:
                snapshot = [
                    (variable, variable.varValue) for variable in problem.variables()
                ]
                last_value = result.objective_value
            elif snapshot is not None:
                for variable, value in snapshot:
                    variable.varValue = value
                status = SolverStatus.FEASIBLE
            accepted_gap = (
                stage.name == "fairness"
                and gap > 0
                and result.status is SolverStatus.GAP_SATISFIED
            )
            approximate_fairness |= accepted_gap
            if result.status is not SolverStatus.OPTIMAL and not accepted_gap:
                message = f"Phase {stage.name} ended as {result.status.value}; hierarchy incomplete."
                break
            if index == len(model.stages) - 1:
                complete = True
                status = (
                    SolverStatus.FEASIBLE
                    if approximate_fairness
                    else SolverStatus.OPTIMAL
                )
                message = (
                    "Hierarchy completed; fairness accepted within its configured MIP gap; achieved score preserved."
                    if approximate_fairness
                    else "All lexicographic phases optimal within numerical tolerances."
                )
                break
            assert result.objective_value is not None
            tolerance = (
                0.0
                if stage.name == "node_cost"
                else model.config.lexicographic_tolerance
            )
            lock_name = f"lexicographic_preserve_{stage.name}"
            constraint = (
                stage.expression <= result.objective_value + tolerance
                if stage.sense == pulp.LpMinimize
                else stage.expression >= result.objective_value - tolerance
            )
            problem.addConstraint(constraint, lock_name)
            locks.append(lock_name)
    finally:
        for lock_name in locks:
            del problem.constraints[lock_name]
        # Keep the public problem consistent with the last returned incumbent.
        if records:
            last_feasible = [r for r in records if r.objective_value is not None]
            if last_feasible:
                stage = next(
                    s for s in model.stages if s.name == last_feasible[-1].name
                )
                problem.setObjective(stage.expression)
                problem.sense = stage.sense
    return SolverResult(
        status,
        last_value,
        perf_counter() - started,
        name,
        tuple(records),
        complete,
        message,
    )
