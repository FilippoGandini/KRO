"""Focused tests for effective-demand linearization and runtime capacity."""

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
from kubernetes_resource_optimizer.optimization.model import (
    OptimizationModel,
    build_model,
)
from kubernetes_resource_optimizer.optimization.solver import CbcSolver, SolverStatus

START = datetime(2026, 8, 1, tzinfo=UTC)
ZERO_RISK = OptimizationConfig(0, 0, 0, 0, 1.5, 1.5)


def make_data(
    *,
    nodes: tuple[Node, ...],
    usage: dict[str, list[tuple[float, float]]],
    request_max: tuple[float, float] = (20.0, 20_000.0),
) -> InputData:
    pods = tuple(
        Pod(
            pod_id,
            cpu_request_max=request_max[0],
            memory_request_max=request_max[1],
            cpu_limit_max=request_max[0],
            memory_limit_max=request_max[1],
        )
        for pod_id in usage
    )
    return InputData(
        nodes=nodes,
        pods=pods,
        usage_samples=tuple(
            UsageSample(START + timedelta(hours=index), pod_id, cpu, memory)
            for pod_id, samples in usage.items()
            for index, (cpu, memory) in enumerate(samples)
        ),
    )


def solve(built: OptimizationModel) -> SolverStatus:
    return CbcSolver().solve(built.problem).status


def force_request(
    built: OptimizationModel, pod_id: str, resource: Resource, value: float
) -> None:
    built.problem.addConstraint(
        built.variables.request[pod_id, resource] == value,
        f"force_request_{pod_id}_{resource.value}",
    )


def test_x_zero_allows_effective_demand_to_be_zero() -> None:
    data = make_data(
        nodes=(Node("unused", 10, 10_000), Node("used", 10, 10_000)),
        usage={"pod": [(3, 300)]},
    )
    built = build_model(data, ZERO_RISK)
    q = built.variables.effective_demand["pod", "unused", START, Resource.CPU]
    built.problem.addConstraint(built.variables.placement["pod", "unused"] == 0)
    built.problem.addConstraint(q == 0)

    assert solve(built) is SolverStatus.OPTIMAL
    assert q.varValue == pytest.approx(0)
    assert q.lowBound == 0


def test_x_one_and_usage_below_request_enforces_request() -> None:
    data = make_data(nodes=(Node("node", 10, 10_000),), usage={"pod": [(2, 200)]})
    built = build_model(data, ZERO_RISK)
    force_request(built, "pod", Resource.CPU, 4)
    q = built.variables.effective_demand["pod", "node", START, Resource.CPU]
    built.problem.setObjective(q)

    assert solve(built) is SolverStatus.OPTIMAL
    assert q.varValue == pytest.approx(4)


def test_x_one_and_usage_above_request_enforces_usage() -> None:
    data = make_data(nodes=(Node("node", 10, 10_000),), usage={"pod": [(5, 200)]})
    built = build_model(data, OptimizationConfig(1, 0, 0, 0, 1.5, 1.5))
    force_request(built, "pod", Resource.CPU, 2)
    q = built.variables.effective_demand["pod", "node", START, Resource.CPU]
    built.problem.setObjective(q)

    assert solve(built) is SolverStatus.OPTIMAL
    assert q.varValue == pytest.approx(5)


@pytest.mark.parametrize(
    ("resource", "node", "usage"),
    [
        (Resource.CPU, Node("node", 3, 10_000), (4, 100)),
        (Resource.MEMORY, Node("node", 10, 300), (1, 400)),
    ],
)
def test_runtime_capacity_rejects_resource_overload(
    resource: Resource, node: Node, usage: tuple[float, float]
) -> None:
    built = build_model(make_data(nodes=(node,), usage={"pod": [usage]}), ZERO_RISK)

    assert solve(built) is SolverStatus.INFEASIBLE, resource


def test_placement_feasibility_is_checked_in_every_scenario() -> None:
    data = make_data(
        nodes=(Node("small", 5, 10_000), Node("large", 8, 10_000)),
        usage={"pod": [(0, 100), (7, 100)]},
    )
    built = build_model(data, OptimizationConfig(0.5, 0, 0, 0, 1.5, 1.5))
    force_request(built, "pod", Resource.CPU, 0)

    assert solve(built) is SolverStatus.OPTIMAL
    assert built.variables.placement["pod", "small"].varValue == pytest.approx(0)
    assert built.variables.placement["pod", "large"].varValue == pytest.approx(1)


def test_simultaneous_effective_demands_force_two_nodes() -> None:
    data = make_data(
        nodes=(Node("node-a", 6, 10_000), Node("node-b", 6, 10_000)),
        usage={"pod-a": [(4, 100)], "pod-b": [(4, 100)]},
    )
    built = build_model(data, ZERO_RISK)

    assert solve(built) is SolverStatus.OPTIMAL
    assert sum(v.varValue for v in built.variables.node_active.values()) == pytest.approx(2)
    assert (
        built.variables.placement["pod-a", "node-a"].varValue
        + built.variables.placement["pod-b", "node-a"].varValue
        == pytest.approx(1)
    )


@pytest.mark.parametrize(
    ("pod_count", "node_count", "scenario_count", "expected_variables", "expected_constraints"),
    [
        (1, 1, 1, 16, 28),
        (1, 2, 2, 30, 60),
        (2, 2, 1, 40, 79),
    ],
)
def test_model_size_is_reported_for_focused_instances(
    pod_count: int,
    node_count: int,
    scenario_count: int,
    expected_variables: int,
    expected_constraints: int,
) -> None:
    data = make_data(
        nodes=tuple(Node(f"node-{j}", 10, 10_000) for j in range(node_count)),
        usage={
            f"pod-{i}": [(1, 100)] * scenario_count for i in range(pod_count)
        },
    )
    built = build_model(data, ZERO_RISK)

    assert len(built.problem.variables()) == expected_variables
    assert built.problem.numConstraints() == expected_constraints
    assert all(q.lowBound == 0 for q in built.variables.effective_demand.values())
    assert built.problem.sense == pulp.LpMinimize
