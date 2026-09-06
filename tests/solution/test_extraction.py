"""Known-solution tests for structured extraction and diagnostics."""

from datetime import UTC, datetime, timedelta

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
    SolverResult,
    SolverStatus,
)
from kubernetes_resource_optimizer.solution import extract_solution

START = datetime(2026, 8, 1, tzinfo=UTC)
CONFIG = OptimizationConfig(0.5, 0.5, 0.5, 0.5, 2.0, 2.0)


def make_data() -> InputData:
    return InputData(
        nodes=(Node("node-a", 4.0, 4000.0), Node("node-b", 4.0, 4000.0)),
        pods=(
            Pod(
                "pod-a",
                cpu_request_max=4.0,
                memory_request_max=4000.0,
                cpu_limit_max=4.0,
                memory_limit_max=4000.0,
            ),
            Pod(
                "pod-b",
                cpu_request_max=4.0,
                memory_request_max=4000.0,
                cpu_limit_max=4.0,
                memory_limit_max=4000.0,
            ),
        ),
        usage_samples=(
            UsageSample(START, "pod-a", 1.0, 100.0),
            UsageSample(START, "pod-b", 0.5, 200.0),
            UsageSample(START + timedelta(hours=1), "pod-a", 3.0, 300.0),
            UsageSample(START + timedelta(hours=1), "pod-b", 1.0, 400.0),
        ),
    )


def solve_known_configuration() -> tuple[InputData, object, SolverResult]:
    data = make_data()
    built = build_model(data, CONFIG)
    variables = built.variables
    # Fix rightsizing values while leaving placement and node minimization to the MILP.
    fixed_values = {
        ("pod-a", Resource.CPU, "request"): 2.0,
        ("pod-a", Resource.MEMORY, "request"): 250.0,
        ("pod-a", Resource.CPU, "limit"): 3.0,
        ("pod-a", Resource.MEMORY, "limit"): 350.0,
        ("pod-b", Resource.CPU, "request"): 1.0,
        ("pod-b", Resource.MEMORY, "request"): 300.0,
        ("pod-b", Resource.CPU, "limit"): 1.5,
        ("pod-b", Resource.MEMORY, "limit"): 500.0,
    }
    for (pod_id, resource, family), value in fixed_values.items():
        variable = (
            variables.request[pod_id, resource]
            if family == "request"
            else variables.limit[pod_id, resource]
        )
        built.problem.addConstraint(
            variable == value, f"fix_{family}_{pod_id}_{resource.value}"
        )
    result = solve_lexicographic(built, CbcSolver())
    assert result.status is SolverStatus.OPTIMAL
    return data, built, result


def test_extracts_workloads_nodes_and_summary() -> None:
    data, built, solver_result = solve_known_configuration()

    result = extract_solution(data, built, solver_result)

    assert result.solver_status is SolverStatus.OPTIMAL
    assert result.objective_value == pytest.approx(103 / 96)
    assert result.lexicographic_complete
    assert result.stages == solver_result.stages
    assert result.active_node_count == 1
    assert result.total_node_cost == pytest.approx(1.0)
    assert result.solve_time_seconds == solver_result.solve_time_seconds
    assert [(item.workload_id, item.assigned_node) for item in result.workloads] == [
        ("pod-a", result.workloads[0].assigned_node),
        ("pod-b", result.workloads[0].assigned_node),
    ]
    assert result.workloads[0].recommended_cpu_request == pytest.approx(2.0)
    assert result.workloads[0].recommended_memory_limit == pytest.approx(350.0)

    active_node = next(node for node in result.nodes if node.active)
    inactive_node = next(node for node in result.nodes if not node.active)
    assert active_node.assigned_workloads == ("pod-a", "pod-b")
    assert active_node.cost == pytest.approx(1.0)
    assert inactive_node.assigned_workloads == ()


def test_calculates_actual_violation_rates_and_node_diagnostics() -> None:
    data, built, solver_result = solve_known_configuration()

    result = extract_solution(data, built, solver_result)
    violation = {
        (item.workload_id, item.resource): item for item in result.violations
    }

    assert violation["pod-a", Resource.CPU].request_violation_count == 1
    assert violation["pod-a", Resource.CPU].request_violation_rate == pytest.approx(0.5)
    assert violation["pod-a", Resource.CPU].limit_violation_count == 0
    assert violation["pod-a", Resource.MEMORY].request_violation_count == 1
    assert violation["pod-a", Resource.MEMORY].limit_violation_count == 0
    assert violation["pod-b", Resource.CPU].request_violation_rate == 0
    assert violation["pod-b", Resource.MEMORY].request_violation_rate == pytest.approx(0.5)

    active = next(
        item
        for item in result.node_diagnostics
        if next(node for node in result.nodes if node.node_id == item.node_id).active
    )
    inactive = next(item for item in result.node_diagnostics if item.node_id != active.node_id)
    assert active.peak_effective_cpu == pytest.approx(4.0)
    assert active.peak_effective_memory == pytest.approx(700.0)
    assert active.configured_cpu_limit_overcommit == pytest.approx(4.5 / 4.0)
    assert active.configured_memory_limit_overcommit == pytest.approx(850.0 / 4000.0)
    assert inactive.peak_effective_cpu == 0
    assert inactive.peak_effective_memory == 0
    assert inactive.configured_cpu_limit_overcommit == 0
    assert inactive.configured_memory_limit_overcommit == 0


def test_rejects_extraction_without_a_feasible_solution() -> None:
    data = make_data()
    built = build_model(data, CONFIG)
    unsolved = SolverResult(SolverStatus.INFEASIBLE, None, 0.1)

    with pytest.raises(ValueError, match="cannot extract"):
        extract_solution(data, built, unsolved)
