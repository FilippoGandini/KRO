"""Smoke tests for the MILP solver boundary."""

import pulp
import pytest

from kubernetes_resource_optimizer.optimization.solver import (
    CbcSolver,
    HighsSolver,
    SolverName,
    SolverStatus,
    _normalize_status,
    create_solver,
)


def test_cbc_solves_tiny_binary_milp() -> None:
    model = pulp.LpProblem("tiny_binary_milp", pulp.LpMinimize)
    first = model.add_variable("first", cat=pulp.LpBinary)
    second = model.add_variable("second", cat=pulp.LpBinary)
    model += first + second
    model += first + 2 * second >= 1.5, "minimum_coverage"

    result = CbcSolver().solve(model)

    assert result.status is SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(1.0)
    assert first.varValue == pytest.approx(0.0)
    assert second.varValue == pytest.approx(1.0)
    assert result.solve_time_seconds >= 0
    assert result.solver is SolverName.CBC
    assert model.get_constraint_by_name("minimum_coverage") is not None


def test_highs_solves_tiny_binary_milp_in_process() -> None:
    model = pulp.LpProblem("tiny_highs_binary_milp", pulp.LpMinimize)
    selected = model.add_variable("selected", cat=pulp.LpBinary)
    model += selected
    model += selected >= 1, "must_select"

    result = HighsSolver().solve(model)

    assert result.status is SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(1.0)
    assert result.solver is SolverName.HIGHS
    assert selected.varValue == pytest.approx(1.0)


def test_integer_feasible_incumbent_is_not_reported_as_optimal() -> None:
    status = _normalize_status(
        pulp.LpStatusOptimal,
        pulp.LpSolutionIntegerFeasible,
    )

    assert status is SolverStatus.FEASIBLE


def test_factory_defaults_to_highs_and_propagates_time_limit() -> None:
    solver = create_solver(time_limit_seconds=12.5)

    assert isinstance(solver, HighsSolver)
    assert solver.time_limit_seconds == 12.5


@pytest.mark.parametrize("solver_type", [HighsSolver, CbcSolver])
@pytest.mark.parametrize("invalid_limit", [0, -1, float("inf"), float("nan")])
def test_all_solvers_reject_invalid_time_limits(
    solver_type: type[HighsSolver] | type[CbcSolver],
    invalid_limit: float,
) -> None:
    with pytest.raises(ValueError, match="time_limit_seconds"):
        solver_type(time_limit_seconds=invalid_limit)
