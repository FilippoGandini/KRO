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


def test_cbc_gap_stop_is_distinct_from_time_stop() -> None:
    from kubernetes_resource_optimizer.optimization.solver import (
        SolverResult,
        _cbc_termination,
    )

    incumbent = SolverResult(SolverStatus.OPTIMAL, 10, 1)
    gap = _cbc_termination(
        incumbent,
        "Result - Optimal solution found (within gap tolerance)\nUpper bound: 10.4\nGap: -0.04\n",
    )
    assert gap.status is SolverStatus.GAP_SATISFIED
    assert gap.mip_gap == pytest.approx(0.04)
    assert gap.best_bound == pytest.approx(10.4)
    timed = _cbc_termination(
        incumbent, "Result - Stopped on time limit\nUpper bound: 12\nGap: -0.2\n"
    )
    assert timed.status is SolverStatus.FEASIBLE


@pytest.mark.parametrize(
    "native_status,gap,target,expected",
    [
        (SolverStatus.OPTIMAL, 0.04, 0.05, SolverStatus.GAP_SATISFIED),
        (SolverStatus.OPTIMAL, 0.0, 0.05, SolverStatus.OPTIMAL),
        (SolverStatus.FEASIBLE, 0.2, 0.05, SolverStatus.FEASIBLE),
        (SolverStatus.OPTIMAL, 0.04, 0.0, SolverStatus.FEASIBLE),
        (SolverStatus.OPTIMAL, 3.5527136788004996e-16, 0.0, SolverStatus.OPTIMAL),
        (SolverStatus.OPTIMAL, 1e-12, 0.0, SolverStatus.OPTIMAL),
        (SolverStatus.OPTIMAL, 1.001e-12, 0.0, SolverStatus.FEASIBLE),
        (SolverStatus.OPTIMAL, 1.001e-12, 0.05, SolverStatus.GAP_SATISFIED),
        (SolverStatus.FEASIBLE, 3.5527136788004996e-16, 0.0, SolverStatus.FEASIBLE),
        (SolverStatus.FEASIBLE, 0.0, 0.05, SolverStatus.FEASIBLE),
    ],
)
def test_highs_native_gap_is_not_misreported_as_exact_optimality(
    monkeypatch, native_status, gap, target, expected
) -> None:
    from types import SimpleNamespace

    import kubernetes_resource_optimizer.optimization.solver as adapter

    model = pulp.LpProblem("native_status")

    def native_solve(problem, command, solver):
        problem.solverModel = SimpleNamespace(
            getInfo=lambda: SimpleNamespace(mip_gap=gap, mip_dual_bound=10.4)
        )
        return adapter.SolverResult(native_status, 10, 1, solver)

    monkeypatch.setattr(adapter, "_solve", native_solve)
    result = HighsSolver(mip_gap=target).solve(model)
    assert result.status is expected
    assert result.mip_gap == gap
    assert result.best_bound == 10.4
