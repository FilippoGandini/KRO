"""Tests for limit-placement linearization and node limit overcommit."""

from datetime import UTC, datetime

import pytest

from kubernetes_resource_optimizer.data.models import (
    InputData,
    Node,
    Pod,
    Resource,
    UsageSample,
)
from kubernetes_resource_optimizer.optimization.config import OptimizationConfig
from kubernetes_resource_optimizer.optimization.model import (
    OptimizationModel,
    build_model,
)
from kubernetes_resource_optimizer.optimization.solver import CbcSolver, SolverStatus

TIMESTAMP = datetime(2026, 8, 1, tzinfo=UTC)


def make_data(*, node_count: int = 1, pod_count: int = 1) -> InputData:
    pods = tuple(
        Pod(
            f"pod-{index}",
            cpu_request_max=10,
            memory_request_max=1_000,
            cpu_limit_max=10,
            memory_limit_max=1_000,
        )
        for index in range(pod_count)
    )
    return InputData(
        nodes=tuple(Node(f"node-{index}", 10, 1_000) for index in range(node_count)),
        pods=pods,
        usage_samples=tuple(UsageSample(TIMESTAMP, pod.pod_id, 1, 100) for pod in pods),
    )


def config(cpu: float, memory: float) -> OptimizationConfig:
    return OptimizationConfig(0, 0, 0, 0, cpu, memory, limit_peak_multiplier=10)


def solve(built: OptimizationModel) -> SolverStatus:
    return CbcSolver().solve(built.problem).status


def force_limit(
    built: OptimizationModel, pod_id: str, resource: Resource, value: float
) -> None:
    built.problem.addConstraint(
        built.variables.limit[pod_id, resource] == value,
        f"force_limit_{pod_id}_{resource.value}",
    )


def test_x_zero_forces_placed_limit_to_zero() -> None:
    built = build_model(make_data(node_count=2), config(2, 2))
    placed_limit = built.variables.placed_limit["pod-0", "node-0", Resource.CPU]
    force_limit(built, "pod-0", Resource.CPU, 4)
    built.problem.addConstraint(built.variables.placement["pod-0", "node-0"] == 0)

    assert solve(built) is SolverStatus.OPTIMAL
    assert placed_limit.varValue == pytest.approx(0)
    assert placed_limit.lowBound == 0


def test_x_one_forces_placed_limit_to_equal_limit() -> None:
    built = build_model(make_data(), config(2, 2))
    placed_limit = built.variables.placed_limit["pod-0", "node-0", Resource.CPU]
    force_limit(built, "pod-0", Resource.CPU, 4)

    assert solve(built) is SolverStatus.OPTIMAL
    assert built.variables.placement["pod-0", "node-0"].varValue == pytest.approx(1)
    assert placed_limit.varValue == pytest.approx(4)


def test_cpu_limit_overcommit_factor_is_parametric() -> None:
    data = make_data(pod_count=2)

    strict = build_model(data, config(1, 2))
    permissive = build_model(data, config(1.2, 2))
    for built in (strict, permissive):
        for pod_id in ("pod-0", "pod-1"):
            force_limit(built, pod_id, Resource.CPU, 6)

    assert solve(strict) is SolverStatus.INFEASIBLE
    assert solve(permissive) is SolverStatus.OPTIMAL


def test_aggregate_limits_over_bound_make_forced_placement_infeasible() -> None:
    built = build_model(make_data(node_count=2, pod_count=2), config(1, 2))
    for pod_id in ("pod-0", "pod-1"):
        force_limit(built, pod_id, Resource.CPU, 6)
        built.problem.addConstraint(
            built.variables.placement[pod_id, "node-0"] == 1,
            f"force_{pod_id}_onto_node_0",
        )

    assert solve(built) is SolverStatus.INFEASIBLE


def test_cpu_and_memory_overcommit_factors_may_differ() -> None:
    data = make_data(pod_count=2)
    memory_strict = build_model(data, config(1.2, 1))
    both_permissive = build_model(data, config(1.2, 1.2))
    for built in (memory_strict, both_permissive):
        for pod_id in ("pod-0", "pod-1"):
            force_limit(built, pod_id, Resource.CPU, 6)
            force_limit(built, pod_id, Resource.MEMORY, 600)

    assert solve(memory_strict) is SolverStatus.INFEASIBLE
    assert solve(both_permissive) is SolverStatus.OPTIMAL
