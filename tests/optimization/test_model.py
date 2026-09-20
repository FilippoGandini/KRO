"""Deterministic tests for the first MILP model-building stage."""

from datetime import UTC, datetime

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
from kubernetes_resource_optimizer.optimization.solver import CbcSolver, SolverStatus

TIMESTAMP = datetime(2026, 8, 1, tzinfo=UTC)
ZERO_RISK = OptimizationConfig(0, 0, 0, 0, 1.5, 1.5)


def make_data(*, pod_count: int, node_count: int) -> InputData:
    pods = tuple(
        Pod(
            f"pod-{index}",
            cpu_request_max=2.0,
            memory_request_max=2048.0,
            cpu_limit_max=4.0,
            memory_limit_max=4096.0,
        )
        for index in range(pod_count)
    )
    return InputData(
        nodes=tuple(Node(f"node-{index}", 8.0, 8192.0) for index in range(node_count)),
        pods=pods,
        usage_samples=tuple(
            UsageSample(TIMESTAMP, pod.pod_id, 1.0, 1024.0) for pod in pods
        ),
    )


def test_one_pod_one_node_uses_the_only_node() -> None:
    built = build_model(make_data(pod_count=1, node_count=1), ZERO_RISK)

    result = solve_lexicographic(built, CbcSolver())

    assert result.status is SolverStatus.OPTIMAL
    assert result.stages[0].objective_value == pytest.approx(1.0)
    assert built.variables.placement["pod-0", "node-0"].varValue == pytest.approx(1.0)
    assert built.variables.node_active["node-0"].varValue == pytest.approx(1.0)


def test_two_pods_two_nodes_minimizes_to_one_active_node() -> None:
    built = build_model(make_data(pod_count=2, node_count=2), ZERO_RISK)

    result = solve_lexicographic(built, CbcSolver())

    assert result.status is SolverStatus.OPTIMAL
    assert result.stages[0].objective_value == pytest.approx(1.0)
    assert sum(
        variable.varValue for variable in built.variables.node_active.values()
    ) == pytest.approx(1.0)


def test_every_pod_is_assigned_exactly_once() -> None:
    built = build_model(make_data(pod_count=2, node_count=2), ZERO_RISK)
    solve_lexicographic(built, CbcSolver())

    for pod_id in ("pod-0", "pod-1"):
        assert sum(
            built.variables.placement[pod_id, node_id].varValue
            for node_id in ("node-0", "node-1")
        ) == pytest.approx(1.0)


def test_inactive_node_cannot_host_a_pod() -> None:
    built = build_model(make_data(pod_count=1, node_count=1), ZERO_RISK)
    built.problem.addConstraint(
        built.variables.node_active["node-0"] == 0, "force_inactive"
    )
    built.problem.addConstraint(
        built.variables.placement["pod-0", "node-0"] == 1, "force_placement"
    )

    result = solve_lexicographic(built, CbcSolver())

    assert result.status is SolverStatus.INFEASIBLE


@pytest.mark.parametrize("resource", list(Resource))
def test_request_cannot_exceed_limit(resource: Resource) -> None:
    built = build_model(make_data(pod_count=1, node_count=1), ZERO_RISK)
    built.problem.addConstraint(
        built.variables.limit["pod-0", resource]
        == built.requests["pod-0", resource] / 2,
        "force_limit_below_request",
    )

    result = solve_lexicographic(built, CbcSolver())

    assert result.status is SolverStatus.INFEASIBLE


def test_request_and_limit_variables_use_derived_upper_bounds() -> None:
    built = build_model(make_data(pod_count=1, node_count=1), ZERO_RISK)

    assert built.variables.limit["pod-0", Resource.CPU].lowBound == 0
    assert built.variables.limit["pod-0", Resource.CPU].upBound == 1.5
    assert built.variables.limit["pod-0", Resource.MEMORY].upBound == 1536.0


def test_model_contains_all_expected_variable_families() -> None:
    built = build_model(make_data(pod_count=2, node_count=2), ZERO_RISK)

    assert len(built.problem.variables()) == 22
    assert all(
        variable.name.startswith(
            (
                "placement_",
                "node_active_",
                "limit_",
                "limit_violation_",
                "placed_limit_",
                "minimum_limit_headroom_",
            )
        )
        for variable in built.problem.variables()
    )
    assert built.problem.sense == pulp.LpMinimize
    assert [stage.name for stage in built.stages] == ["node_cost", "weighted_limits"]


def test_limit_headroom_is_distributed_fairly_with_deterministic_requests() -> None:
    pods = tuple(
        Pod(
            f"pod-{index}",
            cpu_request_max=10,
            memory_request_max=1000,
            cpu_limit_max=10,
            memory_limit_max=1000,
        )
        for index in range(2)
    )
    data = InputData(
        nodes=(Node("node-0", 10, 1000),),
        pods=pods,
        usage_samples=tuple(UsageSample(TIMESTAMP, pod.pod_id, 1, 100) for pod in pods),
    )
    config = OptimizationConfig(0, 0, 0, 0, 1, 1, fairness=True)
    built = build_model(data, config)

    result = solve_lexicographic(built, CbcSolver())

    assert result.status is SolverStatus.OPTIMAL
    for pod in pods:
        assert built.requests[pod.pod_id, Resource.CPU] == pytest.approx(1)
        assert built.requests[pod.pod_id, Resource.MEMORY] == pytest.approx(100)
        assert built.variables.limit[
            pod.pod_id, Resource.CPU
        ].varValue == pytest.approx(1.5)
        assert built.variables.limit[
            pod.pod_id, Resource.MEMORY
        ].varValue == pytest.approx(150)
    assert built.variables.minimum_limit_headroom[
        Resource.CPU
    ].varValue == pytest.approx(1 / 3)
    assert built.variables.minimum_limit_headroom[
        Resource.MEMORY
    ].varValue == pytest.approx(1 / 3)


def test_node_cost_is_primary_with_deterministic_requests() -> None:
    data = make_data(pod_count=1, node_count=2)
    data = InputData(
        nodes=(Node("cheap", 8, 8192, 0.10), Node("expensive", 8, 8192, 0.11)),
        pods=data.pods,
        usage_samples=data.usage_samples,
    )
    built = build_model(data, ZERO_RISK)

    result = solve_lexicographic(built, CbcSolver())

    assert result.status is SolverStatus.OPTIMAL
    assert built.variables.placement["pod-0", "cheap"].varValue == pytest.approx(1)


def test_optimizer_can_choose_more_nodes_when_their_total_cost_is_lower() -> None:
    data = make_data(pod_count=2, node_count=1)
    data = InputData(
        nodes=(
            Node("large", 8, 8192, 10),
            Node("small-a", 1, 1024, 3),
            Node("small-b", 1, 1024, 3),
        ),
        pods=data.pods,
        usage_samples=data.usage_samples,
    )
    built = build_model(data, ZERO_RISK)

    result = solve_lexicographic(built, CbcSolver())

    assert result.status is SolverStatus.OPTIMAL
    assert built.variables.node_active["large"].varValue == pytest.approx(0)
    assert built.variables.node_active["small-a"].varValue == pytest.approx(1)
    assert built.variables.node_active["small-b"].varValue == pytest.approx(1)
