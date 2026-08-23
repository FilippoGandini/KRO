"""Smoke tests for the MILP solver boundary."""

import pulp
import pytest

from kubernetes_resource_optimizer.optimization.solver import (
    CbcSolver,
    SolverStatus,
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
    assert model.get_constraint_by_name("minimum_coverage") is not None
