"""End-to-end hierarchy, optional fairness, and interruption handling."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pulp
import pytest

from kubernetes_resource_optimizer.data.models import (
    InputData,
    Node,
    Pod,
    Resource,
    UsageSample,
)
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.model import build_model
from kubernetes_resource_optimizer.optimization.objectives.lexicographic import (
    solve_lexicographic,
)
from kubernetes_resource_optimizer.optimization.solver import (
    CbcSolver,
    HighsSolver,
    SolverResult,
    SolverStatus,
)

CONFIG = OptimizationConfig(0.25, 0, 0.25, 0, 1, 1)


def data() -> InputData:
    return InputData(
        (Node("cheap", 10, 100, 1), Node("expensive", 10, 100, 2)),
        (Pod("steady"), Pod("spiky")),
        tuple(
            UsageSample(
                datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=t), pod, value, 10
            )
            for pod, values in [("steady", [2, 2, 2, 2]), ("spiky", [0, 0, 1, 8])]
            for t, value in enumerate(values)
        ),
    )


@pytest.mark.parametrize("solver_type", [CbcSolver, HighsSolver])
@pytest.mark.parametrize("priority, expected", [(-2, (9, 1)), (2, (2, 8))])
def test_priority_changes_limits_without_sacrificing_cost_or_requests(
    solver_type, priority, expected
) -> None:
    model = build_model(data(), replace(CONFIG, limit_priority=priority))
    result = solve_lexicographic(model, solver_type())
    assert result.status is SolverStatus.OPTIMAL
    assert result.lexicographic_complete
    assert [s.name for s in result.stages] == [
        "node_cost",
        "normalized_requests",
        "weighted_limits",
    ]
    assert result.stages[0].objective_value == pytest.approx(1)
    assert result.stages[1].objective_value == pytest.approx(0.5)
    assert model.variables.minimum_limit_headroom == {}
    assert [
        model.variables.limit[pod, Resource.CPU].varValue for pod in ("steady", "spiky")
    ] == pytest.approx(expected)
    assert [
        model.variables.request[pod, Resource.CPU].varValue
        for pod in ("steady", "spiky")
    ] == pytest.approx([2, 1])
    # Temporary locks do not contaminate repeat solves.
    again = solve_lexicographic(model, solver_type())
    assert again.objective_value == pytest.approx(result.objective_value)


@pytest.mark.parametrize("priority", [-2, 2])
def test_fairness_precedes_weights(priority: int) -> None:
    model = build_model(data(), replace(CONFIG, fairness=True, limit_priority=priority))
    result = solve_lexicographic(model, HighsSolver())
    assert result.lexicographic_complete
    assert result.stages[2].name == "fairness"
    assert result.stages[2].objective_value == pytest.approx(0.75)
    assert [
        model.variables.limit[pod, Resource.CPU].varValue for pod in ("steady", "spiky")
    ] == pytest.approx([5.5, 4.5])
    assert sum(
        v.varValue for v in model.variables.minimum_limit_headroom.values()
    ) == pytest.approx(0.75)


def test_zero_upper_bounds_and_zero_reward_remain_solvable() -> None:
    source = data()
    source = replace(
        source,
        pods=tuple(
            replace(
                p,
                cpu_request_max=0,
                memory_request_max=0,
                cpu_limit_max=0,
                memory_limit_max=0,
            )
            for p in source.pods
        ),
        usage_samples=tuple(
            replace(s, cpu_usage=0, memory_usage=0) for s in source.usage_samples
        ),
    )
    model = build_model(source, replace(CONFIG, fairness=True))
    result = solve_lexicographic(model, HighsSolver())
    assert result.lexicographic_complete
    assert [s.objective_value for s in result.stages] == pytest.approx([1, 0, 0, 0])


def test_no_later_phase_after_feasible_but_unproven_result(monkeypatch) -> None:
    calls = []
    original = HighsSolver.solve

    def interrupted(self, problem):
        result = original(self, problem)
        calls.append(result)
        return replace(result, status=SolverStatus.FEASIBLE)

    monkeypatch.setattr(HighsSolver, "solve", interrupted)
    result = solve_lexicographic(build_model(data(), CONFIG), HighsSolver())
    assert len(calls) == 1
    assert result.status is SolverStatus.FEASIBLE
    assert not result.lexicographic_complete
    assert "incomplete" in result.message


def test_later_no_incumbent_restores_prior_feasible_values(monkeypatch) -> None:
    model = build_model(data(), CONFIG)
    original = HighsSolver.solve
    calls = 0
    saved = {}

    def interrupted(self, problem):
        nonlocal calls
        calls += 1
        if calls == 1:
            result = original(self, problem)
            saved.update({v.name: v.varValue for v in problem.variables()})
            return result
        for variable in problem.variables():
            variable.varValue = None
        return SolverResult(SolverStatus.NOT_SOLVED, None, 0)

    monkeypatch.setattr(HighsSolver, "solve", interrupted)
    result = solve_lexicographic(model, HighsSolver())
    assert result.status is SolverStatus.FEASIBLE
    assert not result.lexicographic_complete
    assert {v.name: v.varValue for v in model.problem.variables()} == saved
    assert pulp.value(model.problem.objective) == pytest.approx(result.objective_value)


def test_nonzero_mip_gap_is_not_misrepresented_as_exact_hierarchy() -> None:
    with pytest.raises(ValueError, match="mip_gap"):
        solve_lexicographic(build_model(data(), CONFIG), HighsSolver(mip_gap=0.1))


def test_only_fairness_optimum_is_locked_not_intermediate_limits(monkeypatch) -> None:
    from kubernetes_resource_optimizer.optimization.objectives.stages import (
        ObjectiveStage,
    )

    problem = pulp.LpProblem("redistribute", pulp.LpMinimize)
    first = problem.add_variable("first_limit", lowBound=2)
    second = problem.add_variable("second_limit", lowBound=2)
    fairness = problem.add_variable("fairness", lowBound=0, upBound=2)
    problem += first + second <= 10
    problem += fairness <= first
    problem += fairness <= second
    stages = (
        ObjectiveStage("node_cost", pulp.LpAffineExpression(), pulp.LpMinimize),
        ObjectiveStage(
            "normalized_requests", pulp.LpAffineExpression(), pulp.LpMinimize
        ),
        ObjectiveStage("fairness", fairness + 0, pulp.LpMaximize),
        ObjectiveStage("weighted_limits", second + 0, pulp.LpMaximize),
    )
    model = replace(
        build_model(data(), replace(CONFIG, fairness=True)),
        problem=problem,
        stages=stages,
    )
    original = HighsSolver.solve
    count = 0

    def choose_valid_fairness_optimum(self, current):
        nonlocal count
        count += 1
        if count == 3:
            # One valid fairness-optimal allocation, deliberately poor for phase 4.
            current.addConstraint(first == 8, "temporary_test_choice")
        result = original(self, current)
        if count == 3:
            assert first.varValue == pytest.approx(8)
            del current.constraints["temporary_test_choice"]
        return result

    monkeypatch.setattr(HighsSolver, "solve", choose_valid_fairness_optimum)
    result = solve_lexicographic(model, HighsSolver())
    assert result.lexicographic_complete
    assert fairness.varValue == pytest.approx(2)
    assert first.varValue == pytest.approx(2)
    assert second.varValue == pytest.approx(8)


def test_time_budget_is_shared_across_phases(monkeypatch) -> None:
    import kubernetes_resource_optimizer.optimization.objectives.lexicographic as workflow

    clock = [0.0]
    budgets = []
    monkeypatch.setattr(workflow, "perf_counter", lambda: clock[0])
    original = HighsSolver.solve

    def timed(self, problem):
        budgets.append(self.time_limit_seconds)
        result = original(self, problem)
        clock[0] += 2
        return result

    monkeypatch.setattr(HighsSolver, "solve", timed)
    result = solve_lexicographic(
        build_model(data(), CONFIG), HighsSolver(time_limit_seconds=3)
    )
    assert budgets == [3, 1]
    assert result.status is SolverStatus.FEASIBLE
    assert not result.lexicographic_complete
    assert "before weighted_limits" in result.message
    assert result.solve_time_seconds == 4
