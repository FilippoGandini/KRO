"""Manual-optimum tests for request and limit chance constraints."""

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
from kubernetes_resource_optimizer.optimization.solver import CbcSolver, SolverStatus


def make_usage_data(cpu: list[float], memory: list[float]) -> InputData:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    return InputData(
        nodes=(Node("node-0", 16.0, 65536.0),),
        pods=(
            Pod(
                "pod-0",
                cpu_request_max=16.0,
                memory_request_max=65536.0,
                cpu_limit_max=16.0,
                memory_limit_max=65536.0,
            ),
        ),
        usage_samples=tuple(
            UsageSample(
                start + timedelta(hours=index), "pod-0", cpu_value, memory_value
            )
            for index, (cpu_value, memory_value) in enumerate(
                zip(cpu, memory, strict=True)
            )
        ),
    )


def solve_minimum_resources(
    data: InputData, config: OptimizationConfig
) -> tuple[object, object]:
    """Use a test-only objective so the chance-constraint threshold is unique."""

    built = build_model(data, config)
    built.problem.setObjective(pulp.lpSum(built.variables.limit.values()))
    result = CbcSolver().solve(built.problem)
    assert result.status is SolverStatus.OPTIMAL
    return built, result


def test_zero_epsilon_requires_request_and_limit_to_cover_every_scenario() -> None:
    built, _ = solve_minimum_resources(
        make_usage_data([1.0, 3.0, 2.0], [100.0, 300.0, 200.0]),
        OptimizationConfig(0, 0, 0, 0, 1.5, 1.5),
    )

    assert built.requests["pod-0", Resource.CPU] == pytest.approx(3.0)
    assert built.variables.limit["pod-0", Resource.CPU].varValue == pytest.approx(3.0)
    assert built.requests["pod-0", Resource.MEMORY] == pytest.approx(300.0)
    assert built.variables.limit["pod-0", Resource.MEMORY].varValue == pytest.approx(
        300.0
    )
    assert sum(
        variable.varValue for variable in built.variables.limit_violation.values()
    ) == pytest.approx(0)


def test_exactly_one_permitted_violation_selects_second_highest_values() -> None:
    built, _ = solve_minimum_resources(
        make_usage_data([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]),
        OptimizationConfig(0.25, 0.25, 0.25, 0.25, 1.5, 1.5),
    )

    assert built.requests["pod-0", Resource.CPU] == pytest.approx(3.0)
    assert built.variables.limit["pod-0", Resource.CPU].varValue == pytest.approx(3.0)
    assert built.requests["pod-0", Resource.MEMORY] == pytest.approx(30.0)
    assert built.variables.limit["pod-0", Resource.MEMORY].varValue == pytest.approx(
        30.0
    )


def test_multiple_violations_and_resources_are_independently_configured() -> None:
    built, _ = solve_minimum_resources(
        make_usage_data([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0]),
        OptimizationConfig(0.5, 0.25, 0.25, 0.5, 1.5, 1.5),
    )

    # CPU request permits two violations while its limit permits one.
    assert built.requests["pod-0", Resource.CPU] == pytest.approx(2.0)
    assert built.variables.limit["pod-0", Resource.CPU].varValue == pytest.approx(3.0)
    # Memory reverses those independent risk tolerances.
    assert built.requests["pod-0", Resource.MEMORY] == pytest.approx(30.0)
    # request <= limit raises the more permissive memory limit to the request.
    assert built.variables.limit["pod-0", Resource.MEMORY].varValue == pytest.approx(
        30.0
    )
    for resource in Resource:
        assert (
            built.requests["pod-0", resource]
            <= built.variables.limit["pod-0", resource].varValue
        )


def test_violation_variables_are_binary_and_indexed_by_scenario_and_resource() -> None:
    data = make_usage_data([1.0, 2.0, 3.0], [10.0, 20.0, 30.0])
    built = build_model(data, OptimizationConfig(0, 0, 0, 0, 1.5, 1.5))

    assert len(built.variables.limit_violation) == 6
    assert all(
        variable.lowBound == 0 and variable.upBound == 1
        for variable in built.variables.limit_violation.values()
    )
