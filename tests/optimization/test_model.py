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


def test_one_workload_one_node_uses_the_only_node() -> None:
    built = build_model(make_data(pod_count=1, node_count=1), ZERO_RISK)

    result = CbcSolver().solve(built.problem)

    assert result.status is SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(4.0)
    assert built.variables.placement["pod-0", "node-0"].varValue == pytest.approx(1.0)
    assert built.variables.node_active["node-0"].varValue == pytest.approx(1.0)


def test_two_workloads_two_nodes_minimizes_to_one_active_node() -> None:
    built = build_model(make_data(pod_count=2, node_count=2), ZERO_RISK)

    result = CbcSolver().solve(built.problem)

    assert result.status is SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(7.0)
    assert sum(variable.varValue for variable in built.variables.node_active.values()) == pytest.approx(1.0)


def test_every_workload_is_assigned_exactly_once() -> None:
    built = build_model(make_data(pod_count=2, node_count=2), ZERO_RISK)
    CbcSolver().solve(built.problem)

    for pod_id in ("pod-0", "pod-1"):
        assert sum(
            built.variables.placement[pod_id, node_id].varValue
            for node_id in ("node-0", "node-1")
        ) == pytest.approx(1.0)


def test_inactive_node_cannot_host_a_workload() -> None:
    built = build_model(make_data(pod_count=1, node_count=1), ZERO_RISK)
    built.problem.addConstraint(
        built.variables.node_active["node-0"] == 0, "force_inactive"
    )
    built.problem.addConstraint(
        built.variables.placement["pod-0", "node-0"] == 1, "force_placement"
    )

    result = CbcSolver().solve(built.problem)

    assert result.status is SolverStatus.INFEASIBLE


@pytest.mark.parametrize("resource", list(Resource))
def test_request_cannot_exceed_limit(resource: Resource) -> None:
    built = build_model(make_data(pod_count=1, node_count=1), ZERO_RISK)
    built.problem.addConstraint(
        built.variables.request["pod-0", resource] == 2.0, "force_request"
    )
    built.problem.addConstraint(
        built.variables.limit["pod-0", resource] == 1.0, "force_limit"
    )

    result = CbcSolver().solve(built.problem)

    assert result.status is SolverStatus.INFEASIBLE


def test_request_and_limit_variables_use_derived_upper_bounds() -> None:
    built = build_model(make_data(pod_count=1, node_count=1), ZERO_RISK)

    assert built.variables.request["pod-0", Resource.CPU].lowBound == 0
    assert built.variables.request["pod-0", Resource.CPU].upBound == 2.0
    assert built.variables.request["pod-0", Resource.MEMORY].upBound == 2048.0
    assert built.variables.limit["pod-0", Resource.CPU].lowBound == 0
    assert built.variables.limit["pod-0", Resource.CPU].upBound == 4.0
    assert built.variables.limit["pod-0", Resource.MEMORY].upBound == 4096.0


def test_model_contains_all_expected_variable_families() -> None:
    built = build_model(make_data(pod_count=2, node_count=2), ZERO_RISK)

    assert len(built.problem.variables()) == 38
    assert all(
        variable.name.startswith(
            (
                "placement_",
                "node_active_",
                "request_",
                "limit_",
                "request_violation_",
                "limit_violation_",
                "effective_demand_",
                "placed_limit_",
            )
        )
        for variable in built.problem.variables()
    )
    assert built.problem.sense == pulp.LpMinimize
    assert built.problem.objective.name == "minimum_active_nodes_and_requests"
